"""Sitemap intelligence service.

Responsibilities (safe, official-only):
- List/get/submit/delete sitemap *submissions* via the official GSC Sitemaps API.
- Detect sitemaps from robots.txt Sitemap directives and common paths.
- Download a sitemap safely, parse it, and cross-reference the latest crawl to
  raise deterministic SitemapIssue records (404/5xx/redirect/noindex/non-canonical
  /duplicate/invalid/outside-property).

It never edits the website's sitemap file. Editing the actual sitemap.xml or
robots.txt is handled by the repo-agent / PR workflow after admin approval.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit
from uuid import UUID
from xml.etree import ElementTree

import httpx
import structlog

from app.core.config import settings
from app.models.search_console import GSCPropertySourceType
from app.models.sitemap import (
    GSCSitemapRecord,
    SitemapIssueSeverity,
    SitemapIssueStatus,
    SitemapIssueType,
    SitemapSource,
    SitemapStatus,
)
from app.repositories.search_console import SearchConsoleRepository
from app.repositories.sitemap import SitemapRepository, _url_key
from app.services.search_console import (
    GoogleSearchConsoleClient,
    SearchConsoleConfigurationError,
    SearchConsoleError,
)

logger = structlog.get_logger(__name__)

COMMON_SITEMAP_PATHS = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/wp-sitemap.xml",
]

_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


class SitemapServiceError(SearchConsoleError):
    """Raised when a sitemap operation cannot complete."""


@dataclass
class ParsedSitemap:
    is_index: bool
    urls: List[str] = field(default_factory=list)
    child_sitemaps: List[str] = field(default_factory=list)
    parse_error: Optional[str] = None


@dataclass
class FetchResult:
    status_code: int
    text: str
    content_length: int
    error: Optional[str] = None


class SitemapIntelligenceService:
    """Coordinates sitemap detection, GSC submission, and safe analysis."""

    def __init__(
        self,
        db,
        google_client: Optional[GoogleSearchConsoleClient] = None,
    ):
        self.db = db
        self.repository = SitemapRepository(db)
        self.sc_repository = SearchConsoleRepository(db)
        self.google_client = google_client or GoogleSearchConsoleClient()

    # ---- read -----------------------------------------------------------------

    async def list_sitemaps(self, project_id: UUID, tenant_id: UUID) -> List[GSCSitemapRecord]:
        await self._require_project(project_id, tenant_id)
        return await self.repository.list_sitemaps(project_id, tenant_id)

    async def list_issues(self, project_id: UUID, tenant_id: UUID, *, status: Optional[str] = None):
        await self._require_project(project_id, tenant_id)
        status_enum = SitemapIssueStatus(status) if status else None
        return await self.repository.list_issues(project_id, tenant_id, status=status_enum)

    # ---- GSC Sitemaps API -----------------------------------------------------

    async def refresh(self, project_id: UUID, tenant_id: UUID) -> List[GSCSitemapRecord]:
        """List submitted sitemaps from the GSC Sitemaps API and persist them."""
        project = await self._require_project(project_id, tenant_id)
        prop, connection = await self._require_oauth_property(project_id, tenant_id)
        access_token = await self._access_token(connection)
        site_url = self._site_url_for_api(prop)
        try:
            entries = await self.google_client.list_sitemaps(access_token, site_url)
        except SearchConsoleError:
            raise
        records: List[GSCSitemapRecord] = []
        for entry in entries:
            record = await self._upsert_from_gsc_entry(project_id, tenant_id, prop.id, entry)
            records.append(record)
        await self.db.commit()
        return await self.repository.list_sitemaps(project_id, tenant_id)

    async def submit(self, project_id: UUID, tenant_id: UUID, sitemap_url: str) -> GSCSitemapRecord:
        """Submit a sitemap URL to GSC (write scope). Persists only on API success."""
        project = await self._require_project(project_id, tenant_id)
        prop, connection = await self._require_oauth_property(project_id, tenant_id)
        normalized = self._normalize_sitemap_url(sitemap_url)
        if not self._url_in_property(prop, normalized):
            raise SitemapServiceError(
                "Sitemap URL is not inside the selected Search Console property. "
                "Submit a sitemap that lives on the verified property domain/prefix."
            )
        access_token = await self._access_token(connection)
        site_url = self._site_url_for_api(prop)
        # GSC API success is required before we claim "submitted".
        await self.google_client.submit_sitemap(access_token, site_url, normalized)
        record = await self.repository.upsert_sitemap(
            project_id=project_id,
            tenant_id=tenant_id,
            sitemap_url=normalized,
            values={
                "property_id": prop.id,
                "is_submitted": True,
                "is_pending": True,
                "source": SitemapSource.gsc_api,
                "status": SitemapStatus.active,
                "last_submitted_at": datetime.utcnow(),
            },
        )
        await self.db.commit()
        await self.db.refresh(record)
        logger.info("Sitemap submitted to GSC", project_id=str(project_id), sitemap_url=normalized)
        return record

    async def delete(self, sitemap_id: UUID, tenant_id: UUID) -> GSCSitemapRecord:
        """Delete a sitemap submission from GSC (write scope), then mark deleted."""
        record = await self.repository.get_sitemap(sitemap_id, tenant_id)
        if not record:
            raise ValueError("Sitemap not found")
        prop, connection = await self._require_oauth_property(record.project_id, tenant_id)
        access_token = await self._access_token(connection)
        site_url = self._site_url_for_api(prop)
        await self.google_client.delete_sitemap(access_token, site_url, record.sitemap_url)
        record = await self.repository.mark_deleted(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record

    # ---- detection (no Google needed) -----------------------------------------

    async def detect(self, project_id: UUID, tenant_id: UUID) -> List[GSCSitemapRecord]:
        """Detect sitemaps from robots.txt directives and common paths."""
        project = await self._require_project(project_id, tenant_id)
        base = self._project_base_url(project)
        if not base:
            raise ValueError("Project has no valid domain to detect sitemaps from")

        found: Dict[str, str] = {}  # url -> discovery note

        # robots.txt Sitemap: directives
        robots = await self._http_get(urljoin(base + "/", "robots.txt"))
        if robots.status_code and 200 <= robots.status_code < 300 and robots.text:
            for directive in self._robots_sitemaps(robots.text):
                found.setdefault(self._normalize_sitemap_url(directive), "robots.txt")

        # common paths
        for path in COMMON_SITEMAP_PATHS:
            candidate = urljoin(base + "/", path.lstrip("/"))
            if candidate in found:
                continue
            head = await self._http_get(candidate)
            if head.status_code and 200 <= head.status_code < 300 and self._looks_like_xml(head.text):
                found.setdefault(candidate, f"common path {path}")

        records: List[GSCSitemapRecord] = []
        for url, note in found.items():
            existing = await self.repository.get_by_url(project_id, tenant_id, url)
            values = {
                "source": existing.source if existing and existing.source == SitemapSource.gsc_api else SitemapSource.detected,
                "status": SitemapStatus.active if not (existing and existing.status == SitemapStatus.deleted) else SitemapStatus.active,
                "raw_payload": {"discovered_via": note},
            }
            record = await self.repository.upsert_sitemap(
                project_id=project_id,
                tenant_id=tenant_id,
                sitemap_url=url,
                values=values,
            )
            records.append(record)
        await self.db.commit()
        return await self.repository.list_sitemaps(project_id, tenant_id)

    # ---- analysis (download + parse + validate) -------------------------------

    async def analyze(
        self,
        project_id: UUID,
        tenant_id: UUID,
        *,
        sitemap_id: Optional[UUID] = None,
        sitemap_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Download and validate sitemaps, then (re)generate open issues."""
        project = await self._require_project(project_id, tenant_id)

        targets: List[GSCSitemapRecord] = []
        if sitemap_id:
            record = await self.repository.get_sitemap(sitemap_id, tenant_id)
            if not record:
                raise ValueError("Sitemap not found")
            targets = [record]
        elif sitemap_url:
            url = self._normalize_sitemap_url(sitemap_url)
            record = await self.repository.get_by_url(project_id, tenant_id, url)
            if not record:
                record = await self.repository.upsert_sitemap(
                    project_id=project_id,
                    tenant_id=tenant_id,
                    sitemap_url=url,
                    values={"source": SitemapSource.detected, "status": SitemapStatus.active},
                )
            targets = [record]
        else:
            targets = await self.repository.list_sitemaps(project_id, tenant_id)
            if not targets:
                targets = await self.detect(project_id, tenant_id)

        crawl_pages = await self.repository.latest_crawl_pages(project_id, tenant_id)
        selected_prop = await self.sc_repository.selected_property(project_id, tenant_id)

        total_issues = 0
        analyzed = 0
        for record in targets:
            if record.status == SitemapStatus.deleted:
                continue
            issues = await self._analyze_one(record, project, crawl_pages, selected_prop)
            total_issues += issues
            analyzed += 1
        await self.db.commit()
        return {
            "analyzed_sitemaps": analyzed,
            "issues_created": total_issues,
            "sitemaps": await self.repository.list_sitemaps(project_id, tenant_id),
        }

    async def _analyze_one(
        self,
        record: GSCSitemapRecord,
        project: Any,
        crawl_pages: Dict[str, Any],
        selected_prop: Any,
    ) -> int:
        await self.repository.clear_open_issues(record.id)
        fetched = await self._http_get(record.sitemap_url)
        record.last_downloaded_at = datetime.utcnow()

        issues: List[dict] = []

        if not fetched.status_code or fetched.status_code >= 400 or fetched.error:
            issues.append(self._issue(
                record, SitemapIssueType.fetch_error, SitemapIssueSeverity.critical,
                "Sitemap could not be downloaded",
                f"Fetching {record.sitemap_url} returned status {fetched.status_code or 'no response'}"
                f"{': ' + fetched.error if fetched.error else ''}.",
                "Ensure the sitemap URL is publicly reachable and returns HTTP 200 with XML content.",
            ))
            await self._persist_issues(record, issues, status=SitemapStatus.error, errors=len(issues))
            return len(issues)

        parsed = self._parse_sitemap(fetched.text)
        if parsed.parse_error:
            issues.append(self._issue(
                record, SitemapIssueType.parse_error, SitemapIssueSeverity.high,
                "Sitemap XML could not be parsed",
                f"Parser error: {parsed.parse_error}",
                "Fix the sitemap XML so it is valid per the sitemaps.org schema.",
            ))
            await self._persist_issues(record, issues, status=SitemapStatus.error, errors=len(issues))
            return len(issues)

        record.is_sitemaps_index = parsed.is_index
        entries = parsed.child_sitemaps if parsed.is_index else parsed.urls
        record.submitted_urls_count = len(entries)

        if not entries:
            issues.append(self._issue(
                record, SitemapIssueType.empty_sitemap, SitemapIssueSeverity.medium,
                "Sitemap contains no URLs",
                "The sitemap parsed successfully but lists zero URLs.",
                "Add the site's important, indexable URLs to the sitemap.",
            ))

        # Only validate page URLs (not child sitemap indexes) against the crawl.
        if not parsed.is_index:
            issues.extend(self._validate_urls(record, parsed.urls, project, crawl_pages, selected_prop))

        # GSC-side signal: submitted but not in GSC / not submitted.
        if selected_prop is not None and not record.is_submitted:
            issues.append(self._issue(
                record, SitemapIssueType.missing_in_gsc, SitemapIssueSeverity.medium,
                "Sitemap not submitted to Search Console",
                "This sitemap was detected on the site but is not submitted to the selected GSC property.",
                "Submit this sitemap to Google Search Console so Google discovers it during crawling.",
            ))

        warnings = sum(1 for i in issues if i["severity"] in (SitemapIssueSeverity.low, SitemapIssueSeverity.medium))
        errors = sum(1 for i in issues if i["severity"] in (SitemapIssueSeverity.high, SitemapIssueSeverity.critical))
        status = SitemapStatus.error if errors else (SitemapStatus.warning if warnings else SitemapStatus.active)
        await self._persist_issues(record, issues, status=status, errors=errors, warnings=warnings)
        return len(issues)

    def _validate_urls(
        self,
        record: GSCSitemapRecord,
        urls: List[str],
        project: Any,
        crawl_pages: Dict[str, Any],
        selected_prop: Any,
    ) -> List[dict]:
        issues: List[dict] = []
        seen: set[str] = set()
        duplicates: List[str] = []
        invalid: List[str] = []
        non_https: List[str] = []
        outside: List[str] = []
        not_found: List[str] = []
        server_error: List[str] = []
        redirects: List[str] = []
        noindex: List[str] = []
        non_canonical: List[str] = []

        for url in urls:
            key = _url_key(url)
            if key in seen:
                duplicates.append(url)
                continue
            seen.add(key)

            parts = urlsplit(url)
            if parts.scheme not in ("http", "https") or not parts.netloc:
                invalid.append(url)
                continue
            if parts.scheme != "https":
                non_https.append(url)
            if selected_prop is not None and not self._url_in_property(selected_prop, url):
                outside.append(url)

            page = crawl_pages.get(key)
            if page is not None:
                code = getattr(page, "status_code", None)
                if code is not None:
                    if code >= 500:
                        server_error.append(url)
                    elif code == 404 or code == 410:
                        not_found.append(url)
                    elif 300 <= code < 400 or getattr(page, "redirect_count", 0):
                        redirects.append(url)
                if getattr(page, "noindex", False):
                    noindex.append(url)
                canonical = getattr(page, "canonical_url_normalized", None) or getattr(page, "canonical_url", None)
                if canonical and _url_key(canonical) != key:
                    non_canonical.append(url)

        def add(issue_type, severity, title, description, action, sample):
            if sample:
                issues.append(self._issue(record, issue_type, severity, title, description, action, sample_urls=sample[:10]))

        add(SitemapIssueType.duplicate_url, SitemapIssueSeverity.low,
            f"{len(duplicates)} duplicate URL(s) in sitemap",
            "The sitemap lists the same URL more than once.",
            "Remove duplicate <loc> entries so each URL appears once.", duplicates)
        add(SitemapIssueType.invalid_url, SitemapIssueSeverity.high,
            f"{len(invalid)} invalid URL(s) in sitemap",
            "Some entries are not valid absolute http(s) URLs.",
            "Replace invalid entries with absolute, correctly-formed URLs.", invalid)
        add(SitemapIssueType.non_https_url, SitemapIssueSeverity.medium,
            f"{len(non_https)} non-HTTPS URL(s) in sitemap",
            "Some sitemap URLs use http:// instead of https://.",
            "List the canonical HTTPS URLs in the sitemap.", non_https)
        add(SitemapIssueType.url_outside_property, SitemapIssueSeverity.high,
            f"{len(outside)} URL(s) outside the selected property",
            "Some sitemap URLs are not inside the verified GSC property.",
            "Only include URLs that belong to the verified property.", outside)
        add(SitemapIssueType.url_not_found, SitemapIssueSeverity.high,
            f"{len(not_found)} URL(s) return 404/410 (live crawl check)",
            "Our crawler observed these sitemap URLs returning not-found responses.",
            "Remove dead URLs from the sitemap or restore the pages.", not_found)
        add(SitemapIssueType.url_server_error, SitemapIssueSeverity.high,
            f"{len(server_error)} URL(s) return 5xx (live crawl check)",
            "Our crawler observed server errors for these sitemap URLs.",
            "Fix the server errors, then keep the URLs in the sitemap.", server_error)
        add(SitemapIssueType.url_redirects, SitemapIssueSeverity.medium,
            f"{len(redirects)} URL(s) redirect (live crawl check)",
            "Our crawler observed redirects for these sitemap URLs.",
            "List the final destination URL in the sitemap instead of a redirecting URL.", redirects)
        add(SitemapIssueType.url_noindex, SitemapIssueSeverity.high,
            f"{len(noindex)} noindex URL(s) in sitemap (live crawl check)",
            "Our crawler observed a noindex signal on these sitemap URLs.",
            "Either remove the noindex tag (if the page should be indexable) or remove the URL from the sitemap.", noindex)
        add(SitemapIssueType.url_non_canonical, SitemapIssueSeverity.medium,
            f"{len(non_canonical)} non-canonical URL(s) in sitemap (live crawl check)",
            "These sitemap URLs declare a different canonical URL.",
            "List the canonical URL in the sitemap so Google's and your canonical agree.", non_canonical)
        return issues

    async def _persist_issues(
        self,
        record: GSCSitemapRecord,
        issues: List[dict],
        *,
        status: SitemapStatus,
        errors: int = 0,
        warnings: int = 0,
    ) -> None:
        for values in issues:
            await self.repository.add_issue(values)
        record.errors_count = errors
        record.warnings_count = warnings
        record.status = status
        record.updated_at = datetime.utcnow()
        await self.db.flush()

    # ---- helpers --------------------------------------------------------------

    def _issue(
        self,
        record: GSCSitemapRecord,
        issue_type: SitemapIssueType,
        severity: SitemapIssueSeverity,
        title: str,
        description: str,
        recommended_action: str,
        sample_urls: Optional[List[str]] = None,
    ) -> dict:
        return {
            "tenant_id": record.tenant_id,
            "project_id": record.project_id,
            "sitemap_id": record.id,
            "issue_type": issue_type,
            "severity": severity,
            "title": title,
            "description": description,
            "recommended_action": recommended_action,
            "sample_urls": sample_urls,
            "status": SitemapIssueStatus.open,
        }

    def _parse_sitemap(self, text: str) -> ParsedSitemap:
        try:
            root = ElementTree.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
        except ElementTree.ParseError as exc:
            return ParsedSitemap(is_index=False, parse_error=str(exc))
        tag = root.tag.lower()
        if tag.endswith("sitemapindex"):
            children = [self._loc_text(node) for node in root.findall(f"{_SITEMAP_NS}sitemap")]
            children = [c for c in children if c]
            if not children:  # namespace-less fallback
                children = [self._loc_text(node) for node in root.findall("sitemap") if self._loc_text(node)]
            return ParsedSitemap(is_index=True, child_sitemaps=children)
        # urlset (or unknown -> treat as urlset)
        urls = [self._loc_text(node) for node in root.findall(f"{_SITEMAP_NS}url")]
        urls = [u for u in urls if u]
        if not urls:
            urls = [self._loc_text(node) for node in root.findall("url") if self._loc_text(node)]
        return ParsedSitemap(is_index=False, urls=urls)

    def _loc_text(self, node) -> Optional[str]:
        loc = node.find(f"{_SITEMAP_NS}loc")
        if loc is None:
            loc = node.find("loc")
        if loc is not None and loc.text:
            return loc.text.strip()
        return None

    def _robots_sitemaps(self, robots_text: str) -> List[str]:
        results = []
        for line in robots_text.splitlines():
            match = re.match(r"\s*sitemap\s*:\s*(\S+)", line, re.IGNORECASE)
            if match:
                results.append(match.group(1).strip())
        return results

    def _looks_like_xml(self, text: str) -> bool:
        if not text:
            return False
        head = text.lstrip()[:400].lower()
        return head.startswith("<?xml") or "<urlset" in head or "<sitemapindex" in head

    async def _http_get(self, url: str) -> FetchResult:
        """Safe GET for robots.txt and sitemaps with size/timeout guards."""
        try:
            async with httpx.AsyncClient(
                timeout=settings.GSC_SITEMAP_FETCH_TIMEOUT_SECONDS,
                follow_redirects=True,
                headers={"User-Agent": settings.GSC_SITEMAP_USER_AGENT},
            ) as client:
                response = await client.get(url)
                raw = response.content[: settings.GSC_SITEMAP_MAX_BYTES]
                try:
                    text = raw.decode(response.encoding or "utf-8", errors="replace")
                except (LookupError, UnicodeDecodeError):
                    text = raw.decode("utf-8", errors="replace")
                return FetchResult(status_code=response.status_code, text=text, content_length=len(raw))
        except httpx.RequestError as exc:
            return FetchResult(status_code=0, text="", content_length=0, error=str(exc))

    def _normalize_sitemap_url(self, value: str) -> str:
        trimmed = (value or "").strip()
        if not trimmed:
            raise ValueError("Sitemap URL is required")
        if not re.match(r"^https?://", trimmed, re.IGNORECASE):
            trimmed = f"https://{trimmed}"
        return trimmed

    def _project_base_url(self, project: Any) -> Optional[str]:
        domain = (getattr(project, "domain", "") or "").strip()
        if not domain:
            return None
        if not re.match(r"^https?://", domain, re.IGNORECASE):
            domain = f"https://{domain}"
        parts = urlsplit(domain)
        if not parts.netloc:
            return None
        return f"{parts.scheme}://{parts.netloc}"

    def _url_in_property(self, prop: Any, url: str) -> bool:
        site = str(getattr(prop, "site_url", ""))
        host = (urlsplit(url).hostname or "").lower()
        if site.startswith("sc-domain:"):
            domain = site[len("sc-domain:"):].lower()
            return host == domain or host.endswith("." + domain)
        prefix = site.rstrip("/").lower()
        return url.rstrip("/").lower().startswith(prefix)

    def _site_url_for_api(self, prop: Any) -> str:
        site_url = str(prop.site_url)
        if site_url.startswith("sc-domain:"):
            return site_url
        parts = urlsplit(site_url)
        if parts.scheme and parts.netloc and not site_url.endswith("/") and not parts.query:
            return f"{site_url}/"
        return site_url

    async def _upsert_from_gsc_entry(
        self, project_id: UUID, tenant_id: UUID, property_id: UUID, entry: Dict[str, Any]
    ) -> GSCSitemapRecord:
        path = str(entry.get("path") or "")
        contents = entry.get("contents") or []
        submitted_urls = 0
        for content in contents:
            submitted_urls += int(content.get("submitted") or 0)
        errors = int(entry.get("errors") or 0)
        warnings = int(entry.get("warnings") or 0)
        is_pending = bool(entry.get("isPending"))
        is_index = bool(entry.get("isSitemapsIndex"))
        last_submitted = self._parse_dt(entry.get("lastSubmitted"))
        last_downloaded = self._parse_dt(entry.get("lastDownloaded"))
        status = SitemapStatus.error if errors else (SitemapStatus.warning if warnings else SitemapStatus.active)
        return await self.repository.upsert_sitemap(
            project_id=project_id,
            tenant_id=tenant_id,
            sitemap_url=path,
            values={
                "property_id": property_id,
                "is_submitted": True,
                "is_pending": is_pending,
                "is_sitemaps_index": is_index,
                "last_submitted_at": last_submitted,
                "last_downloaded_at": last_downloaded,
                "errors_count": errors,
                "warnings_count": warnings,
                "submitted_urls_count": submitted_urls,
                "source": SitemapSource.gsc_api,
                "status": status,
                "raw_payload": entry,
            },
        )

    def _parse_dt(self, value: Any) -> Optional[datetime]:
        if not value:
            return None
        text = str(value).replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
            return parsed.replace(tzinfo=None)
        except ValueError:
            return None

    async def _require_project(self, project_id: UUID, tenant_id: UUID):
        project = await self.sc_repository.get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")
        return project

    async def _require_oauth_property(self, project_id: UUID, tenant_id: UUID):
        prop = await self.sc_repository.selected_property(project_id, tenant_id)
        if not prop:
            raise ValueError("No selected Search Console property for this project")
        if prop.source_type == GSCPropertySourceType.manual or not prop.connection_id:
            raise SitemapServiceError(
                "The GSC Sitemaps API requires an OAuth-connected property. "
                "Manual properties cannot submit or list sitemaps via the API."
            )
        connection = await self.sc_repository.get_connection(prop.connection_id, tenant_id)
        if not connection:
            raise SitemapServiceError("Search Console OAuth connection not found")
        return prop, connection

    async def _access_token(self, connection) -> str:
        # Delegates to the shared SearchConsoleService token refresh path.
        from app.services.search_console import SearchConsoleService

        service = SearchConsoleService(self.db, google_client=self.google_client)
        return await service._access_token(connection)
