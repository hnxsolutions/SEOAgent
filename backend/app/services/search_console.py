"""Google Search Console sync, CSV fallback, and opportunity analysis."""
from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlencode, urlsplit, urlunsplit, quote
from uuid import UUID

import httpx
from jose import JWTError, jwt
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import settings
from app.core.encryption import decrypt_secret, encrypt_secret
from app.models.search_console import (
    GSCComparisonWindow,
    GSCConnectionStatus,
    GSCPropertySourceType,
    GSCPropertyType,
    GSCSyncJob,
    GSCSyncJobStatus,
    GSCSyncType,
    SearchConsoleImport,
    SearchConsoleImportStatus,
    SearchConsoleOpportunity,
    SearchConsoleOpportunityStatus,
    SearchConsoleOpportunityType,
    SearchConsolePeriod,
    SearchConsoleRow,
    SearchConsoleSourceType,
)
from app.repositories.search_console import SearchConsoleRepository

logger = structlog.get_logger(__name__)

GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GSC_API_BASE_URL = "https://www.googleapis.com/webmasters/v3"
GSC_URL_INSPECTION_ENDPOINT = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"


class SearchConsoleError(RuntimeError):
    """Base Search Console service error."""


class SearchConsoleConfigurationError(SearchConsoleError):
    """Raised when Google OAuth is not configured."""


class SearchConsoleOAuthError(SearchConsoleError):
    """Raised when OAuth state or token exchange fails."""


class SearchConsoleGoogleAPIError(SearchConsoleError):
    """Raised when the Google Search Console API request fails."""


@dataclass
class AnalysisResult:
    """Opportunity analysis outcome."""

    created: int
    updated: int
    opportunities: List[SearchConsoleOpportunity]


class GoogleSearchConsoleClient:
    """Small official-HTTP client for Google OAuth and Search Console APIs."""

    def __init__(self, timeout_seconds: float = 30.0, max_retries: int = 2):
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(1, max_retries)

    @property
    def credentials_configured(self) -> bool:
        return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET and settings.GOOGLE_REDIRECT_URI)

    def _require_credentials(self) -> None:
        if not self.credentials_configured:
            raise SearchConsoleConfigurationError(
                "Google Search Console OAuth is disabled until GOOGLE_CLIENT_ID, "
                "GOOGLE_CLIENT_SECRET, and GOOGLE_REDIRECT_URI are configured."
            )

    def build_authorization_url(self, state: str) -> str:
        """Build the Google OAuth authorization URL."""
        self._require_credentials()
        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": GSC_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> Dict[str, Any]:
        """Exchange an OAuth code for Google tokens."""
        self._require_credentials()
        data = {
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        }
        return await self._post_token(data)

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh an access token using a stored refresh token."""
        self._require_credentials()
        data = {
            "refresh_token": refresh_token,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "grant_type": "refresh_token",
        }
        return await self._post_token(data)

    async def _post_token(self, data: Dict[str, Any]) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(GOOGLE_TOKEN_URL, data=data)
                if response.status_code >= 400:
                    raise SearchConsoleOAuthError(f"Google token request failed with status {response.status_code}.")
                payload = response.json()
                if "access_token" not in payload and data.get("grant_type") == "refresh_token":
                    raise SearchConsoleOAuthError("Google token refresh did not return an access token.")
                return payload
            except (httpx.RequestError, SearchConsoleOAuthError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
        raise SearchConsoleOAuthError(str(last_error or "Google token request failed."))

    async def list_sites(self, access_token: str) -> List[Dict[str, Any]]:
        """Fetch verified Search Console sites/properties."""
        payload = await self._request_json("GET", f"{GSC_API_BASE_URL}/sites", access_token)
        return list(payload.get("siteEntry") or [])

    async def fetch_search_analytics(
        self,
        access_token: str,
        site_url: str,
        date_start: datetime,
        date_end: datetime,
        row_limit: int,
        dimensions: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch Search Analytics rows with quota-safe pagination."""
        dimensions = dimensions or ["query", "page", "date", "country", "device", "searchAppearance"]
        try:
            return await self._fetch_search_analytics_page_set(
                access_token=access_token,
                site_url=site_url,
                date_start=date_start,
                date_end=date_end,
                row_limit=row_limit,
                dimensions=dimensions,
            )
        except SearchConsoleGoogleAPIError as exc:
            if "searchAppearance" not in dimensions or "status 400" not in str(exc):
                raise
            fallback_dimensions = [dimension for dimension in dimensions if dimension != "searchAppearance"]
            logger.warning(
                "GSC searchAppearance dimension unavailable; retrying without it",
                site_url=site_url,
                dimensions=fallback_dimensions,
            )
            return await self._fetch_search_analytics_page_set(
                access_token=access_token,
                site_url=site_url,
                date_start=date_start,
                date_end=date_end,
                row_limit=row_limit,
                dimensions=fallback_dimensions,
            )

    async def inspect_url(
        self,
        access_token: str,
        site_url: str,
        inspection_url: str,
        language_code: str = "en-US",
    ) -> Dict[str, Any]:
        """Fetch indexed URL Inspection data for one URL using the official API."""
        body = {
            "inspectionUrl": inspection_url,
            "siteUrl": site_url,
            "languageCode": language_code,
        }
        payload = await self._request_json("POST", GSC_URL_INSPECTION_ENDPOINT, access_token, json=body)
        return dict(payload.get("inspectionResult") or {})

    async def _fetch_search_analytics_page_set(
        self,
        access_token: str,
        site_url: str,
        date_start: datetime,
        date_end: datetime,
        row_limit: int,
        dimensions: List[str],
    ) -> List[Dict[str, Any]]:
        all_rows: List[Dict[str, Any]] = []
        start_row = 0
        encoded_site = quote(site_url, safe="")
        while len(all_rows) < row_limit:
            batch_limit = min(25000, row_limit - len(all_rows))
            body = {
                "startDate": date_start.date().isoformat(),
                "endDate": date_end.date().isoformat(),
                "dimensions": dimensions,
                "rowLimit": batch_limit,
                "startRow": start_row,
            }
            payload = await self._request_json(
                "POST",
                f"{GSC_API_BASE_URL}/sites/{encoded_site}/searchAnalytics/query",
                access_token,
                json=body,
            )
            rows = list(payload.get("rows") or [])
            for row in rows:
                row["_dimensions"] = dimensions
            all_rows.extend(rows)
            if len(rows) < batch_limit:
                break
            start_row += len(rows)
        return all_rows

    async def _request_json(
        self,
        method: str,
        url: str,
        access_token: str,
        json: Optional[dict] = None,
    ) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.request(
                        method,
                        url,
                        headers={"Authorization": f"Bearer {access_token}"},
                        json=json,
                    )
                if response.status_code >= 400:
                    raise SearchConsoleGoogleAPIError(
                        f"Google Search Console request failed with status {response.status_code}."
                    )
                return response.json()
            except (httpx.RequestError, SearchConsoleGoogleAPIError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
        raise SearchConsoleGoogleAPIError(str(last_error or "Google Search Console request failed."))


class SearchConsoleOpportunityAnalyzer:
    """Deterministic rules that turn normalized GSC rows into opportunities."""

    def __init__(
        self,
        high_impressions_threshold: int = settings.GSC_HIGH_IMPRESSIONS_THRESHOLD,
        position_drop_threshold: float = settings.GSC_POSITION_DROP_THRESHOLD,
        ctr_drop_threshold: float = settings.GSC_CTR_DROP_THRESHOLD,
        click_decline_threshold: float = settings.GSC_CLICK_DECLINE_THRESHOLD,
    ):
        self.high_impressions_threshold = high_impressions_threshold
        self.position_drop_threshold = position_drop_threshold
        self.ctr_drop_threshold = ctr_drop_threshold
        self.click_decline_threshold = click_decline_threshold

    def analyze(self, rows: Iterable[SearchConsoleRow], context: Optional[dict] = None) -> List[dict]:
        """Return opportunity records without persisting them."""
        context = context or {}
        current = self._aggregate(rows, SearchConsolePeriod.current)
        previous = self._aggregate(rows, SearchConsolePeriod.previous)
        candidates: List[dict] = []
        for key, row in current.items():
            prev = previous.get(key)
            candidates.extend(self._row_candidates(row, prev, context))
        return candidates

    def _aggregate(self, rows: Iterable[Any], period: SearchConsolePeriod) -> Dict[Tuple[str, str], dict]:
        aggregates: Dict[Tuple[str, str], dict] = {}
        for row in rows:
            row_period = self._enum_value(getattr(row, "period", SearchConsolePeriod.current))
            if row_period != period.value:
                continue
            query = self._clean_query(getattr(row, "query", ""))
            page_url = normalize_url(getattr(row, "page_url", ""))
            if not query or not page_url:
                continue
            key = (query.lower(), page_url)
            impressions = int(getattr(row, "impressions", 0) or 0)
            clicks = int(getattr(row, "clicks", 0) or 0)
            position = float(getattr(row, "position", 0) or 0)
            ctr = float(getattr(row, "ctr", 0) or 0)
            existing = aggregates.get(key)
            if not existing:
                aggregates[key] = {
                    "query": query,
                    "page_url": page_url,
                    "clicks": clicks,
                    "impressions": impressions,
                    "ctr_numerator": ctr * impressions,
                    "position_numerator": position * max(impressions, 1),
                    "position_denominator": max(impressions, 1),
                    "tenant_id": getattr(row, "tenant_id", None),
                    "project_id": getattr(row, "project_id", None),
                    "import_id": getattr(row, "import_id", None),
                    "property_id": getattr(row, "property_id", None),
                    "crawl_page_id": getattr(row, "crawl_page_id", None),
                }
                continue
            existing["clicks"] += clicks
            existing["impressions"] += impressions
            existing["ctr_numerator"] += ctr * impressions
            existing["position_numerator"] += position * max(impressions, 1)
            existing["position_denominator"] += max(impressions, 1)
            if not existing.get("crawl_page_id"):
                existing["crawl_page_id"] = getattr(row, "crawl_page_id", None)
        for item in aggregates.values():
            impressions = max(item["impressions"], 0)
            item["ctr"] = round(item["clicks"] / impressions, 6) if impressions else 0.0
            if not item["ctr"] and item["ctr_numerator"] and impressions:
                item["ctr"] = round(item["ctr_numerator"] / impressions, 6)
            denominator = max(item["position_denominator"], 1)
            item["position"] = round(item["position_numerator"] / denominator, 3)
        return aggregates

    def _row_candidates(self, row: dict, previous: Optional[dict], context: dict) -> List[dict]:
        candidates: List[dict] = []
        expected_ctr = self._expected_ctr(row["position"])
        ctr_gap = max(expected_ctr - row["ctr"], 0)
        if row["impressions"] >= self.high_impressions_threshold and row["ctr"] < expected_ctr * 0.65:
            candidates.append(
                self._candidate(
                    row,
                    previous,
                    SearchConsoleOpportunityType.high_impressions_low_ctr,
                    reason=(
                        f"'{row['query']}' has {row['impressions']} impressions but CTR "
                        f"{row['ctr']:.2%} is below the expected range for position {row['position']:.1f}."
                    ),
                    action="Refresh the SEO title and meta description to better match query intent.",
                    priority=62 + min(28, row["impressions"] / max(self.high_impressions_threshold, 1) * 4) + ctr_gap * 100,
                    confidence=82,
                )
            )
        if 8 <= row["position"] <= 20 and row["impressions"] >= self.high_impressions_threshold:
            candidates.append(
                self._candidate(
                    row,
                    previous,
                    SearchConsoleOpportunityType.striking_distance_keyword,
                    reason=(
                        f"'{row['query']}' ranks at average position {row['position']:.1f}, "
                        "close enough to improve with focused page updates."
                    ),
                    action="Expand the landing page section, add FAQ/answer coverage, and support it with internal links.",
                    priority=70 + max(0, 20 - row["position"]) + min(10, row["impressions"] / 500),
                    confidence=78,
                )
            )
        if previous:
            position_delta = row["position"] - previous["position"]
            if position_delta >= self.position_drop_threshold:
                candidates.append(
                    self._candidate(
                        row,
                        previous,
                        SearchConsoleOpportunityType.ranking_drop,
                        reason=(
                            f"Average position worsened by {position_delta:.1f} "
                            f"from {previous['position']:.1f} to {row['position']:.1f}."
                        ),
                        action="Review content freshness, search intent coverage, and technical SEO signals for this page.",
                        priority=72 + min(18, position_delta * 3),
                        confidence=80,
                    )
                )
            if previous["ctr"] > 0:
                ctr_drop = (previous["ctr"] - row["ctr"]) / previous["ctr"]
                if ctr_drop >= self.ctr_drop_threshold:
                    candidates.append(
                        self._candidate(
                            row,
                            previous,
                            SearchConsoleOpportunityType.ctr_drop,
                            reason=f"CTR dropped by {ctr_drop:.0%} compared with the previous period.",
                            action="Refresh title/meta copy and ensure the snippet clearly answers the query.",
                            priority=68 + min(20, ctr_drop * 30),
                            confidence=79,
                        )
                    )
            if previous["clicks"] > 0:
                click_drop = (previous["clicks"] - row["clicks"]) / previous["clicks"]
                impressions_stable = row["impressions"] >= previous["impressions"] * 0.9
                if click_drop >= self.click_decline_threshold and impressions_stable:
                    candidates.append(
                        self._candidate(
                            row,
                            previous,
                            SearchConsoleOpportunityType.click_decline,
                            reason=(
                                f"Clicks dropped by {click_drop:.0%} while impressions stayed stable or improved."
                            ),
                            action="Investigate snippet CTR, ranking movement, and content freshness for the query/page pair.",
                            priority=70 + min(20, click_drop * 35),
                            confidence=77,
                        )
                    )
            impressions_rising = previous["impressions"] > 0 and row["impressions"] >= previous["impressions"] * 1.2
            clicks_flat = row["clicks"] <= previous["clicks"] * 1.1
            if impressions_rising and clicks_flat:
                candidates.append(
                    self._candidate(
                        row,
                        previous,
                        SearchConsoleOpportunityType.rising_impressions_clicks_flat,
                        reason="Impressions are rising, but clicks are not improving at the same pace.",
                        action="Add clearer answer blocks and expand page copy around this query intent.",
                        priority=66 + min(20, (row["impressions"] - previous["impressions"]) / max(previous["impressions"], 1) * 20),
                        confidence=74,
                    )
                )
        if self._needs_blog_support(row):
            candidates.append(
                self._candidate(
                    row,
                    previous,
                    SearchConsoleOpportunityType.blog_support,
                    reason="The query has informational or commercial intent that can support the target page with a related blog.",
                    action="Create a supporting blog topic that answers the query and links back to the landing page.",
                    priority=64 + min(20, row["impressions"] / max(self.high_impressions_threshold, 1) * 3),
                    confidence=70,
                )
            )
        if self._has_internal_link_signal(row, context):
            candidates.append(
                self._candidate(
                    row,
                    previous,
                    SearchConsoleOpportunityType.internal_link_support,
                    reason="This page has a ranking opportunity and existing internal-link support signals.",
                    action="Add or approve relevant internal links pointing to this page.",
                    priority=69,
                    confidence=72,
                )
            )
        if self._needs_landing_page_expansion(row, context):
            candidates.append(
                self._candidate(
                    row,
                    previous,
                    SearchConsoleOpportunityType.landing_page_expansion,
                    reason="The query suggests service, local, or comparison intent that may need a stronger page section.",
                    action="Expand the landing page with a concise section, FAQ, and proof points for this query.",
                    priority=67,
                    confidence=71,
                )
            )
        return candidates

    def _candidate(
        self,
        row: dict,
        previous: Optional[dict],
        opportunity_type: SearchConsoleOpportunityType,
        reason: str,
        action: str,
        priority: float,
        confidence: float,
    ) -> dict:
        return {
            "tenant_id": row["tenant_id"],
            "project_id": row["project_id"],
            "import_id": row["import_id"],
            "property_id": row["property_id"],
            "crawl_page_id": row.get("crawl_page_id"),
            "query": row["query"],
            "page_url": row["page_url"],
            "opportunity_type": opportunity_type,
            "status": SearchConsoleOpportunityStatus.suggested,
            "current_clicks": int(row["clicks"]),
            "current_impressions": int(row["impressions"]),
            "current_ctr": float(row["ctr"]),
            "current_position": float(row["position"]),
            "previous_clicks": int(previous["clicks"]) if previous else None,
            "previous_impressions": int(previous["impressions"]) if previous else None,
            "previous_ctr": float(previous["ctr"]) if previous else None,
            "previous_position": float(previous["position"]) if previous else None,
            "reason": reason,
            "recommended_action": action,
            "priority_score": round(max(0.0, min(100.0, priority)), 2),
            "confidence_score": round(max(0.0, min(100.0, confidence)), 2),
            "evidence": {
                "expected_ctr": self._expected_ctr(row["position"]),
                "current": {
                    "clicks": int(row["clicks"]),
                    "impressions": int(row["impressions"]),
                    "ctr": float(row["ctr"]),
                    "position": float(row["position"]),
                },
                "previous": {
                    "clicks": int(previous["clicks"]),
                    "impressions": int(previous["impressions"]),
                    "ctr": float(previous["ctr"]),
                    "position": float(previous["position"]),
                }
                if previous
                else None,
            },
        }

    def _expected_ctr(self, position: float) -> float:
        if position <= 1:
            return 0.28
        if position <= 2:
            return 0.15
        if position <= 3:
            return 0.10
        if position <= 5:
            return 0.07
        if position <= 10:
            return 0.04
        if position <= 20:
            return 0.02
        return 0.01

    def _needs_blog_support(self, row: dict) -> bool:
        query = row["query"].lower()
        page = row["page_url"].lower()
        intent_terms = {
            "how",
            "what",
            "why",
            "guide",
            "ideas",
            "tips",
            "best",
            "cost",
            "compare",
            "comparison",
            "vs",
            "examples",
        }
        has_intent = any(re.search(rf"\b{re.escape(term)}\b", query) for term in intent_terms)
        likely_landing = "/blog" not in page and "/article" not in page and "/news" not in page
        return has_intent and likely_landing and row["impressions"] >= self.high_impressions_threshold and row["position"] <= 30

    def _has_internal_link_signal(self, row: dict, context: dict) -> bool:
        page_id = row.get("crawl_page_id")
        if not page_id or row["position"] > 25 or row["impressions"] < self.high_impressions_threshold:
            return False
        for recommendation in context.get("internal_links", []):
            if getattr(recommendation, "target_page_id", None) == page_id:
                return True
        return False

    def _needs_landing_page_expansion(self, row: dict, context: dict) -> bool:
        query = row["query"].lower()
        trigger = any(
            term in query
            for term in [
                "service",
                "services",
                "agency",
                "company",
                "near me",
                "cost",
                "pricing",
                "vs",
                "comparison",
                "best",
            ]
        )
        if not trigger or row["impressions"] < self.high_impressions_threshold or row["position"] > 25:
            return False
        page_id = row.get("crawl_page_id")
        if not page_id:
            return True
        has_page_issue = any(getattr(issue, "crawl_page_id", None) == page_id for issue in context.get("issues", []))
        has_content_suggestion = any(
            getattr(suggestion, "page_id", None) == page_id for suggestion in context.get("content_suggestions", [])
        )
        return has_page_issue or has_content_suggestion

    def _clean_query(self, value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").strip())

    def _enum_value(self, value: Any) -> str:
        return value.value if hasattr(value, "value") else str(value)


class SearchConsoleService:
    """Application service for Search Console OAuth, syncs, CSV imports, and analysis."""

    def __init__(
        self,
        db: AsyncSession,
        google_client: Optional[GoogleSearchConsoleClient] = None,
        analyzer: Optional[SearchConsoleOpportunityAnalyzer] = None,
    ):
        self.db = db
        self.repository = SearchConsoleRepository(db)
        self.google_client = google_client or GoogleSearchConsoleClient()
        self.analyzer = analyzer or SearchConsoleOpportunityAnalyzer()

    def google_oauth_enabled(self) -> bool:
        return self.google_client.credentials_configured

    def build_oauth_start(self, tenant_id: UUID, user_id: UUID) -> dict:
        state = self._encode_oauth_state(tenant_id=tenant_id, user_id=user_id)
        return {
            "authorization_url": self.google_client.build_authorization_url(state),
            "state": state,
            "expires_at": datetime.utcnow() + timedelta(minutes=15),
            "scopes": [GSC_SCOPE],
        }

    async def handle_oauth_callback(self, code: str, state: str) -> dict:
        tenant_id, user_id = self._decode_oauth_state(state)
        user = await self.repository.get_user_in_tenant(user_id, tenant_id)
        if not user:
            raise SearchConsoleOAuthError("OAuth state references a user that is not active in this tenant. Start the Google connection again while signed in.")
        tokens = await self.google_client.exchange_code(code)
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise SearchConsoleOAuthError(
                "Google did not return a refresh token. Reconnect with consent so the agent can sync automatically."
            )
        expires_at = self._expires_at(tokens)
        scopes = str(tokens.get("scope") or GSC_SCOPE).split()
        try:
            connection = await self.repository.upsert_connection(
                tenant_id=tenant_id,
                user_id=user_id,
                encrypted_refresh_token=encrypt_secret(refresh_token),
                access_token_expires_at=expires_at,
                scopes=scopes,
                metadata={"token_type": tokens.get("token_type", "Bearer")},
            )
            await self.db.commit()
            await self.db.refresh(connection)
        except SQLAlchemyError as exc:
            await self.db.rollback()
            logger.warning(
                "Failed to store Google Search Console connection",
                tenant_id=str(tenant_id),
                user_id=str(user_id),
                error=exc.__class__.__name__,
            )
            raise SearchConsoleOAuthError("Google OAuth succeeded, but the connection could not be stored. Check the local user and tenant records.") from exc
        logger.info("Connected Google Search Console", tenant_id=str(tenant_id), user_id=str(user_id))
        return {
            "connection_id": connection.id,
            "tenant_id": tenant_id,
            "status": connection.status,
            "scopes": scopes,
        }

    async def list_properties(
        self,
        tenant_id: UUID,
        user_id: Optional[UUID] = None,
        project_id: Optional[UUID] = None,
        refresh: bool = False,
    ):
        stored = await self.repository.list_properties(tenant_id, project_id=project_id)
        if refresh or not stored:
            connection = await self.repository.latest_connection(tenant_id, user_id=user_id)
            if connection:
                access_token = await self._access_token(connection)
                sites = await self.google_client.list_sites(access_token)
                stored = await self.repository.upsert_properties(connection, sites)
                await self.db.commit()
        return await self.repository.list_properties(tenant_id, project_id=project_id)

    async def select_property(self, project_id: UUID, tenant_id: UUID, property_id: UUID):
        project = await self.repository.get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")
        prop = await self.repository.select_property(project_id, tenant_id, property_id)
        await self.db.commit()
        await self.db.refresh(prop)
        return prop

    async def register_manual_property(
        self,
        project_id: UUID,
        tenant_id: UUID,
        site_url: str,
        property_type: GSCPropertyType,
        notes: Optional[str] = None,
    ):
        project = await self.repository.get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")
        normalized_url = normalize_gsc_property_url(site_url, property_type)
        prop = await self.repository.upsert_manual_property(
            tenant_id=tenant_id,
            project_id=project_id,
            site_url=normalized_url,
            property_type=property_type,
            notes=notes,
        )
        await self.db.commit()
        await self.db.refresh(prop)
        return prop

    async def import_csv(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID],
        filename: str,
        content: bytes,
        date_start: datetime,
        date_end: datetime,
        comparison_window: Optional[GSCComparisonWindow] = None,
    ) -> SearchConsoleImport:
        if project_id and not await self.repository.get_project(project_id, tenant_id):
            raise ValueError("Project not found")
        selected_property = await self.repository.selected_property(project_id, tenant_id) if project_id else None
        import_record = await self.repository.create_import(
            tenant_id=tenant_id,
            project_id=project_id,
            property_id=selected_property.id if selected_property else None,
            source_type=SearchConsoleSourceType.csv_upload,
            filename=filename,
            date_start=date_start,
            date_end=date_end,
            comparison_window=comparison_window,
            metadata={
                "mode": "csv_fallback",
                "property_source_type": (
                    selected_property.source_type.value if selected_property and selected_property.source_type else None
                ),
            },
        )
        await self.repository.set_import_status(import_record, SearchConsoleImportStatus.processing)
        try:
            rows = parse_search_console_csv(
                content=content,
                tenant_id=tenant_id,
                project_id=project_id,
                import_id=import_record.id,
                property_id=selected_property.id if selected_property else None,
                date_start=date_start,
                date_end=date_end,
                comparison_window=comparison_window,
            )
            await self._attach_crawl_pages(rows, tenant_id, project_id)
            count = await self.repository.add_rows(rows)
            await self.repository.finish_import(import_record, count)
            await self.db.commit()
            await self.db.refresh(import_record)
            return import_record
        except Exception as exc:
            await self.repository.set_import_status(import_record, SearchConsoleImportStatus.failed, str(exc))
            await self.db.commit()
            raise

    async def create_sync_job(
        self,
        tenant_id: UUID,
        project_id: UUID,
        sync_type: GSCSyncType = GSCSyncType.manual,
        comparison_window: GSCComparisonWindow = GSCComparisonWindow.last_28_days,
        date_start: Optional[datetime] = None,
        date_end: Optional[datetime] = None,
    ) -> GSCSyncJob:
        project = await self.repository.get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")
        prop = await self.repository.selected_property(project_id, tenant_id)
        if not prop:
            raise ValueError("No selected Search Console property for this project")
        current_start, current_end, _, _ = comparison_dates(comparison_window)
        current_start = date_start or current_start
        current_end = date_end or current_end
        if prop.source_type == GSCPropertySourceType.manual or not prop.connection_id:
            job = await self.repository.create_sync_job(
                tenant_id=tenant_id,
                project_id=project_id,
                connection_id=None,
                property_id=prop.id,
                sync_type=sync_type,
                date_start=current_start,
                date_end=current_end,
                comparison_window=comparison_window,
                status=GSCSyncJobStatus.failed,
                error_message="OAuth connection required for automatic Google Search Console sync. Use CSV fallback for manual properties.",
            )
            await self.db.commit()
            await self.db.refresh(job)
            return job
        connection = await self.repository.get_connection(prop.connection_id, tenant_id)
        if not connection:
            job = await self.repository.create_sync_job(
                tenant_id=tenant_id,
                project_id=project_id,
                connection_id=prop.connection_id,
                property_id=prop.id,
                sync_type=sync_type,
                date_start=current_start,
                date_end=current_end,
                comparison_window=comparison_window,
                status=GSCSyncJobStatus.failed,
                error_message="OAuth connection required for automatic Google Search Console sync.",
            )
            await self.db.commit()
            await self.db.refresh(job)
            return job
        job = await self.repository.create_sync_job(
            tenant_id=tenant_id,
            project_id=project_id,
            connection_id=connection.id,
            property_id=prop.id,
            sync_type=sync_type,
            date_start=current_start,
            date_end=current_end,
            comparison_window=comparison_window,
        )
        await self.db.commit()
        await self.db.refresh(job)
        return job

    async def run_sync_job(self, job_id: UUID, tenant_id: Optional[UUID] = None) -> GSCSyncJob:
        job = await self.repository.get_sync_job(job_id, tenant_id=tenant_id)
        if not job:
            raise ValueError("GSC sync job not found")
        await self.repository.set_sync_job_status(job, GSCSyncJobStatus.running)
        await self.db.commit()
        import_record: Optional[SearchConsoleImport] = None
        try:
            prop = await self.repository.get_property(job.property_id, job.tenant_id)
            if not prop:
                raise ValueError("GSC property not found")
            if prop.source_type == GSCPropertySourceType.manual or not job.connection_id:
                message = (
                    "OAuth connection required for automatic Google Search Console sync. "
                    "Use CSV fallback for manual properties."
                )
                await self.repository.set_sync_job_status(job, GSCSyncJobStatus.failed, message)
                await self.db.commit()
                await self.db.refresh(job)
                return job
            connection = await self.repository.get_connection(job.connection_id, job.tenant_id)
            if not connection:
                raise ValueError("Connected Google Search Console account not found")
            current_start, current_end, previous_start, previous_end = comparison_dates(job.comparison_window)
            if job.date_start and job.date_end:
                current_start = job.date_start
                current_end = job.date_end
                delta = current_end.date() - current_start.date()
                previous_end = current_start - timedelta(days=1)
                previous_start = previous_end - timedelta(days=delta.days)
            import_record = await self.repository.create_import(
                tenant_id=job.tenant_id,
                project_id=job.project_id,
                property_id=job.property_id,
                source_type=SearchConsoleSourceType.gsc_api,
                date_start=current_start,
                date_end=current_end,
                comparison_window=job.comparison_window,
                metadata={
                    "mode": "gsc_api_sync",
                    "previous_date_start": previous_start.date().isoformat(),
                    "previous_date_end": previous_end.date().isoformat(),
                },
            )
            await self.repository.set_import_status(import_record, SearchConsoleImportStatus.processing)
            access_token = await self._access_token(connection)
            current_api_rows = await self.google_client.fetch_search_analytics(
                access_token,
                prop.site_url,
                current_start,
                current_end,
                settings.GSC_SYNC_ROW_LIMIT,
                dimensions=["query", "page", "date", "country", "device", "searchAppearance"],
            )
            previous_api_rows = await self.google_client.fetch_search_analytics(
                access_token,
                prop.site_url,
                previous_start,
                previous_end,
                settings.GSC_SYNC_ROW_LIMIT,
                dimensions=["query", "page", "date", "country", "device", "searchAppearance"],
            )
            rows = normalize_gsc_api_rows(
                current_api_rows,
                tenant_id=job.tenant_id,
                project_id=job.project_id,
                import_id=import_record.id,
                property_id=job.property_id,
                date_start=current_start,
                date_end=current_end,
                comparison_window=job.comparison_window,
                period=SearchConsolePeriod.current,
            )
            rows.extend(
                normalize_gsc_api_rows(
                    previous_api_rows,
                    tenant_id=job.tenant_id,
                    project_id=job.project_id,
                    import_id=import_record.id,
                    property_id=job.property_id,
                    date_start=previous_start,
                    date_end=previous_end,
                    comparison_window=job.comparison_window,
                    period=SearchConsolePeriod.previous,
                )
            )
            await self._attach_crawl_pages(rows, job.tenant_id, job.project_id)
            rows_count = await self.repository.add_rows(rows)
            await self.repository.finish_import(import_record, rows_count)
            analysis = await self.analyze_import(import_record.id, job.tenant_id, commit=False)
            await self.repository.finish_sync_job(
                job,
                import_id=import_record.id,
                rows_fetched=rows_count,
                opportunities_created=analysis.created,
                opportunities_updated=analysis.updated,
            )
            await self.db.commit()
            await self.db.refresh(job)
            return job
        except Exception as exc:
            if import_record:
                await self.repository.set_import_status(import_record, SearchConsoleImportStatus.failed, str(exc))
            await self.repository.set_sync_job_status(job, GSCSyncJobStatus.failed, str(exc))
            await self.db.commit()
            logger.error("GSC sync job failed", job_id=str(job.id), error=str(exc), exc_info=True)
            raise

    async def sync_project(
        self,
        tenant_id: UUID,
        project_id: UUID,
        sync_type: GSCSyncType = GSCSyncType.manual,
        comparison_window: GSCComparisonWindow = GSCComparisonWindow.last_28_days,
        date_start: Optional[datetime] = None,
        date_end: Optional[datetime] = None,
    ) -> GSCSyncJob:
        job = await self.create_sync_job(
            tenant_id=tenant_id,
            project_id=project_id,
            sync_type=sync_type,
            comparison_window=comparison_window,
            date_start=date_start,
            date_end=date_end,
        )
        if job.status == GSCSyncJobStatus.failed:
            await self.db.commit()
            await self.db.refresh(job)
            return job
        return await self.run_sync_job(job.id, tenant_id=tenant_id)

    async def analyze_import(
        self,
        import_id: UUID,
        tenant_id: UUID,
        commit: bool = True,
    ) -> AnalysisResult:
        import_record = await self.repository.get_import(import_id, tenant_id)
        if not import_record:
            raise ValueError("Search Console import not found")
        rows = await self.repository.rows_for_analysis(import_id, tenant_id)
        page_ids = [row.crawl_page_id for row in rows if row.crawl_page_id]
        context = await self.repository.signal_context(tenant_id, import_record.project_id, list(set(page_ids)))
        records = self.analyzer.analyze(rows, context=context)
        created = 0
        updated = 0
        opportunities: List[SearchConsoleOpportunity] = []
        for record in records:
            existing = await self.repository.find_open_opportunity(
                tenant_id=tenant_id,
                project_id=record["project_id"],
                query=record["query"],
                page_url=record["page_url"],
                opportunity_type=record["opportunity_type"],
            )
            if existing:
                opportunity = await self.repository.update_opportunity(existing, record)
                updated += 1
            else:
                opportunity = await self.repository.create_opportunity(record)
                created += 1
            opportunities.append(opportunity)
        if commit:
            await self.db.commit()
            for opportunity in opportunities:
                await self.db.refresh(opportunity)
        return AnalysisResult(created=created, updated=updated, opportunities=opportunities)

    async def list_imports(self, tenant_id: UUID, project_id: Optional[UUID] = None, limit: int = 100, offset: int = 0):
        return await self.repository.list_imports(tenant_id, project_id=project_id, limit=limit, offset=offset)

    async def get_import(self, import_id: UUID, tenant_id: UUID):
        return await self.repository.get_import(import_id, tenant_id)

    async def list_rows(
        self,
        import_id: UUID,
        tenant_id: UUID,
        period: Optional[SearchConsolePeriod] = None,
        limit: int = 100,
        offset: int = 0,
    ):
        import_record = await self.repository.get_import(import_id, tenant_id)
        if not import_record:
            raise ValueError("Search Console import not found")
        return await self.repository.list_rows(import_id, tenant_id, period=period, limit=limit, offset=offset)

    async def list_sync_jobs(self, project_id: UUID, tenant_id: UUID, limit: int = 100, offset: int = 0):
        return await self.repository.list_sync_jobs(project_id, tenant_id, limit=limit, offset=offset)

    async def list_opportunities(
        self,
        tenant_id: UUID,
        import_id: Optional[UUID] = None,
        project_id: Optional[UUID] = None,
        status: Optional[SearchConsoleOpportunityStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ):
        return await self.repository.list_opportunities(
            tenant_id=tenant_id,
            import_id=import_id,
            project_id=project_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def update_opportunity_status(
        self,
        opportunity_id: UUID,
        tenant_id: UUID,
        status: SearchConsoleOpportunityStatus,
    ) -> SearchConsoleOpportunity:
        opportunity = await self.repository.get_opportunity(opportunity_id, tenant_id)
        if not opportunity:
            raise ValueError("Search Console opportunity not found")
        opportunity = await self.repository.set_opportunity_status(opportunity, status)
        await self.db.commit()
        await self.db.refresh(opportunity)
        return opportunity

    async def summary(self, project_id: UUID, tenant_id: UUID) -> dict:
        project = await self.repository.get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")
        summary = await self.repository.summary(project_id, tenant_id)
        summary["top_opportunities"] = await self.repository.list_opportunities(
            tenant_id=tenant_id,
            project_id=project_id,
            status=SearchConsoleOpportunityStatus.suggested,
            limit=10,
        )
        return summary

    async def _access_token(self, connection) -> str:
        refresh_token = decrypt_secret(connection.encrypted_refresh_token)
        tokens = await self.google_client.refresh_access_token(refresh_token)
        expires_at = self._expires_at(tokens)
        if expires_at:
            connection.access_token_expires_at = expires_at
        connection.status = GSCConnectionStatus.connected
        return str(tokens["access_token"])

    async def _attach_crawl_pages(self, rows: List[dict], tenant_id: UUID, project_id: Optional[UUID]) -> None:
        urls = list({row["page_url"] for row in rows if row.get("page_url")})
        matched = await self.repository.match_pages_by_urls(tenant_id, project_id, urls)
        for row in rows:
            page = matched.get(row["page_url"])
            if page:
                row["crawl_page_id"] = page.id

    def _encode_oauth_state(self, tenant_id: UUID, user_id: UUID) -> str:
        payload = {
            "type": "gsc_oauth_state",
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
            "exp": datetime.utcnow() + timedelta(minutes=15),
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    def _decode_oauth_state(self, state: str) -> Tuple[UUID, UUID]:
        try:
            payload = jwt.decode(state, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        except JWTError as exc:
            raise SearchConsoleOAuthError("Invalid or expired Google OAuth state.") from exc
        if payload.get("type") != "gsc_oauth_state":
            raise SearchConsoleOAuthError("Invalid Google OAuth state.")
        try:
            return UUID(str(payload["tenant_id"])), UUID(str(payload["user_id"]))
        except (KeyError, ValueError) as exc:
            raise SearchConsoleOAuthError("Google OAuth state is missing tenant or user context.") from exc

    def _expires_at(self, tokens: dict) -> Optional[datetime]:
        try:
            expires_in = int(tokens.get("expires_in") or 0)
        except (TypeError, ValueError):
            return None
        return datetime.utcnow() + timedelta(seconds=expires_in) if expires_in else None


def normalize_url(url: str) -> str:
    """Normalize a URL for deduplication and page matching."""
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if not parsed.scheme:
        parsed = urlsplit(f"https://{raw}")
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


def normalize_gsc_property_url(site_url: str, property_type: GSCPropertyType) -> str:
    """Normalize manually registered GSC property identifiers."""
    raw = (site_url or "").strip()
    if not raw:
        raise ValueError("GSC property URL is required")
    property_type = GSCPropertyType(property_type)
    if property_type == GSCPropertyType.domain:
        domain = raw
        if domain.startswith("sc-domain:"):
            domain = domain.removeprefix("sc-domain:")
        else:
            parsed = urlsplit(domain if re.match(r"^https?://", domain, re.IGNORECASE) else f"https://{domain}")
            domain = parsed.netloc or parsed.path
        domain = domain.strip().strip("/").lower()
        if "/" in domain:
            domain = domain.split("/", 1)[0]
        if not re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", domain):
            raise ValueError("Domain GSC property must be a valid domain, for example sc-domain:example.com")
        return f"sc-domain:{domain}"

    normalized = normalize_url(raw)
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL-prefix GSC property must be a valid http or https URL")
    return normalized


def metric_content_hash(
    query: str,
    page_url: str,
    clicks: int,
    impressions: int,
    ctr: float,
    position: float,
    date_start: datetime,
    date_end: datetime,
    source_type: SearchConsoleSourceType,
    period: SearchConsolePeriod,
    country: Optional[str] = None,
    device: Optional[str] = None,
    search_appearance: Optional[str] = None,
) -> str:
    seed = "|".join(
        [
            re.sub(r"\s+", " ", query.strip().lower()),
            normalize_url(page_url),
            str(int(clicks or 0)),
            str(int(impressions or 0)),
            f"{float(ctr or 0):.6f}",
            f"{float(position or 0):.3f}",
            date_start.date().isoformat(),
            date_end.date().isoformat(),
            source_type.value,
            period.value,
            (country or "").lower(),
            (device or "").lower(),
            (search_appearance or "").lower(),
        ]
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def parse_search_console_csv(
    content: bytes,
    tenant_id: UUID,
    project_id: Optional[UUID],
    import_id: UUID,
    property_id: Optional[UUID],
    date_start: datetime,
    date_end: datetime,
    comparison_window: Optional[GSCComparisonWindow] = None,
) -> List[dict]:
    """Parse CSV fallback data into normalized SearchConsoleRow records."""
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows: List[dict] = []
    for raw in reader:
        query = _pick(raw, "query", "queries", "search term", "top queries")
        page_url = _pick(raw, "page_url", "page", "pages", "url", "landing page")
        if not query or not page_url:
            continue
        clicks = _int(_pick(raw, "clicks"))
        impressions = _int(_pick(raw, "impressions"))
        ctr = _ctr(_pick(raw, "ctr", "average ctr"))
        position = _float(_pick(raw, "position", "average position"))
        country = _clean_optional(_pick(raw, "country"))
        device = _clean_optional(_pick(raw, "device"))
        search_appearance = _clean_optional(_pick(raw, "search_appearance", "search appearance", "searchAppearance"))
        period = _period(_pick(raw, "period", "comparison_period", "comparison window period"))
        row_start = _date(_pick(raw, "date_start", "start date"), default=date_start)
        row_end = _date(_pick(raw, "date_end", "end date"), default=date_end)
        rows.append(
            _row_values(
                tenant_id=tenant_id,
                project_id=project_id,
                import_id=import_id,
                property_id=property_id,
                query=query,
                page_url=page_url,
                clicks=clicks,
                impressions=impressions,
                ctr=ctr,
                position=position,
                date_start=row_start,
                date_end=row_end,
                comparison_window=comparison_window,
                period=period,
                source_type=SearchConsoleSourceType.csv_upload,
                country=country,
                device=device,
                search_appearance=search_appearance,
            )
        )
    return rows


def normalize_gsc_api_rows(
    api_rows: Iterable[dict],
    tenant_id: UUID,
    project_id: Optional[UUID],
    import_id: UUID,
    property_id: Optional[UUID],
    date_start: datetime,
    date_end: datetime,
    comparison_window: Optional[GSCComparisonWindow],
    period: SearchConsolePeriod,
) -> List[dict]:
    """Normalize official GSC API search analytics rows."""
    rows: List[dict] = []
    for item in api_rows:
        keys = item.get("keys") or []
        dimensions = item.get("_dimensions") or ["query", "page"]
        if len(keys) < 2:
            continue
        keyed = {str(dimension): str(keys[index]) for index, dimension in enumerate(dimensions) if index < len(keys)}
        query = keyed.get("query") or str(keys[0])
        page_url = keyed.get("page") or str(keys[1])
        row_start = date_start
        row_end = date_end
        if keyed.get("date"):
            try:
                row_start = row_end = datetime.strptime(keyed["date"], "%Y-%m-%d")
            except ValueError:
                row_start = date_start
                row_end = date_end
        rows.append(
            _row_values(
                tenant_id=tenant_id,
                project_id=project_id,
                import_id=import_id,
                property_id=property_id,
                query=query,
                page_url=page_url,
                clicks=_int(item.get("clicks")),
                impressions=_int(item.get("impressions")),
                ctr=_ctr(item.get("ctr")),
                position=_float(item.get("position")),
                date_start=row_start,
                date_end=row_end,
                comparison_window=comparison_window,
                period=period,
                source_type=SearchConsoleSourceType.gsc_api,
                country=_clean_optional(keyed.get("country")),
                device=_clean_optional(keyed.get("device")),
                search_appearance=_clean_optional(keyed.get("searchAppearance")),
            )
        )
    return rows


def comparison_dates(
    window: GSCComparisonWindow,
    today: Optional[date] = None,
) -> Tuple[datetime, datetime, datetime, datetime]:
    """Return current and previous date ranges for supported comparison windows."""
    today = today or date.today()
    current_end_date = today - timedelta(days=1)
    if window == GSCComparisonWindow.last_7_days:
        current_start_date = current_end_date - timedelta(days=6)
        previous_end_date = current_start_date - timedelta(days=1)
        previous_start_date = previous_end_date - timedelta(days=6)
    elif window == GSCComparisonWindow.current_month:
        current_start_date = current_end_date.replace(day=1)
        previous_end_date = current_start_date - timedelta(days=1)
        previous_start_date = previous_end_date.replace(day=1)
    else:
        current_start_date = current_end_date - timedelta(days=27)
        previous_end_date = current_start_date - timedelta(days=1)
        previous_start_date = previous_end_date - timedelta(days=27)
    return (
        datetime.combine(current_start_date, datetime.min.time()),
        datetime.combine(current_end_date, datetime.min.time()),
        datetime.combine(previous_start_date, datetime.min.time()),
        datetime.combine(previous_end_date, datetime.min.time()),
    )


def _row_values(
    tenant_id: UUID,
    project_id: Optional[UUID],
    import_id: UUID,
    property_id: Optional[UUID],
    query: str,
    page_url: str,
    clicks: int,
    impressions: int,
    ctr: float,
    position: float,
    date_start: datetime,
    date_end: datetime,
    comparison_window: Optional[GSCComparisonWindow],
    period: SearchConsolePeriod,
    source_type: SearchConsoleSourceType,
    country: Optional[str] = None,
    device: Optional[str] = None,
    search_appearance: Optional[str] = None,
) -> dict:
    normalized_url = normalize_url(page_url)
    clean_query = re.sub(r"\s+", " ", (query or "").strip())
    return {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "import_id": import_id,
        "property_id": property_id,
        "crawl_page_id": None,
        "query": clean_query,
        "page_url": normalized_url,
        "clicks": max(0, clicks),
        "impressions": max(0, impressions),
        "ctr": max(0.0, min(1.0, ctr)),
        "position": max(0.0, position),
        "date_start": date_start,
        "date_end": date_end,
        "country": country,
        "device": device,
        "search_appearance": search_appearance,
        "comparison_window": comparison_window,
        "period": period,
        "source_type": source_type,
        "content_hash": metric_content_hash(
            clean_query,
            normalized_url,
            clicks,
            impressions,
            ctr,
            position,
            date_start,
            date_end,
            source_type,
            period,
            country=country,
            device=device,
            search_appearance=search_appearance,
        ),
    }


def _pick(row: dict, *names: str) -> Any:
    normalized = {str(key).strip().lower(): value for key, value in row.items()}
    for name in names:
        if name in normalized:
            return normalized[name]
    return None


def _int(value: Any) -> int:
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _ctr(value: Any) -> float:
    raw = str(value or "").replace(",", "").strip()
    if raw.endswith("%"):
        return _float(raw[:-1]) / 100
    parsed = _float(raw)
    if parsed > 1:
        return parsed / 100
    return parsed


def _period(value: Any) -> SearchConsolePeriod:
    raw = str(value or "").strip().lower()
    if raw in {"previous", "prev", "comparison", "baseline"}:
        return SearchConsolePeriod.previous
    return SearchConsolePeriod.current


def _date(value: Any, default: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    raw = str(value or "").strip()
    if raw:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
    return default


def _clean_optional(value: Any) -> Optional[str]:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text or None
