"""Live site validation.

Fetches a live (deployed) URL and runs real, deterministic checks: HTTP 200,
HTTPS, robots.txt, sitemap.xml, canonical/title/meta/JSON-LD/OpenGraph/Twitter/
favicon tags, compression and cache headers. No provider credentials required —
this validates the actual public site, so it is fully verifiable.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.project import Project
from app.models.site_validation import SiteValidation

logger = structlog.get_logger(__name__)


def _ok(passed: bool, detail: str) -> Dict[str, Any]:
    return {"passed": bool(passed), "detail": detail}


class SiteValidationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def validate(
        self,
        project_id: UUID,
        tenant_id: UUID,
        url: Optional[str] = None,
        deployment_id: Optional[UUID] = None,
    ) -> SiteValidation:
        project = (await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )).scalars().first()
        if not project:
            raise ValueError("Project not found")
        target = self._normalize(url or project.domain)

        checks: Dict[str, Any] = {}
        reachable = False
        http_status: Optional[int] = None
        is_https = target.lower().startswith("https://")
        error_message = None

        async with httpx.AsyncClient(
            timeout=settings.GSC_SITEMAP_FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": settings.GSC_SITEMAP_USER_AGENT, "Accept-Encoding": "gzip, br"},
        ) as client:
            try:
                resp = await client.get(target)
                reachable = True
                http_status = resp.status_code
                final_url = str(resp.url)
                html = resp.text if resp.status_code < 400 else ""
                headers = resp.headers

                checks["http_200"] = _ok(200 <= resp.status_code < 300, f"HTTP {resp.status_code}")
                checks["https"] = _ok(final_url.lower().startswith("https://"), final_url.split("://", 1)[0])
                is_https = final_url.lower().startswith("https://")
                checks["redirects"] = _ok(True, "redirected" if final_url.rstrip("/") != target.rstrip("/") else "no redirect")
                checks["compression"] = _ok(
                    headers.get("content-encoding", "").lower() in {"gzip", "br", "deflate"},
                    headers.get("content-encoding", "none"),
                )
                checks["cache_headers"] = _ok(
                    bool(headers.get("cache-control")), headers.get("cache-control", "missing")
                )
                # On-page SEO tags
                checks["title"] = _ok(bool(re.search(r"<title[^>]*>.+?</title>", html, re.I | re.S)), "")
                checks["meta_description"] = _ok(
                    bool(re.search(r'<meta[^>]+name=["\']description["\']', html, re.I)), ""
                )
                checks["canonical"] = _ok(
                    bool(re.search(r'<link[^>]+rel=["\']canonical["\']', html, re.I)), ""
                )
                checks["json_ld"] = _ok(
                    bool(re.search(r'<script[^>]+type=["\']application/ld\+json["\']', html, re.I)), ""
                )
                checks["open_graph"] = _ok(bool(re.search(r'<meta[^>]+property=["\']og:', html, re.I)), "")
                checks["twitter_card"] = _ok(bool(re.search(r'<meta[^>]+name=["\']twitter:', html, re.I)), "")
                checks["favicon"] = _ok(
                    bool(re.search(r'<link[^>]+rel=["\'][^"\']*icon', html, re.I)),
                    "declared in HTML" if re.search(r'<link[^>]+rel=["\'][^"\']*icon', html, re.I) else "not in HTML",
                )
            except httpx.HTTPError as exc:
                error_message = str(exc)
                checks["http_200"] = _ok(False, f"unreachable: {exc}")

            # robots.txt + sitemap.xml (independent fetches)
            checks["robots_txt"] = await self._check_path(client, target, "/robots.txt")
            checks["sitemap_xml"] = await self._check_path(client, target, "/sitemap.xml")

        passed = sum(1 for c in checks.values() if c.get("passed"))
        total = len(checks)

        validation = SiteValidation(
            tenant_id=tenant_id, project_id=project_id, deployment_id=deployment_id,
            url=target, reachable=reachable, http_status=http_status, is_https=is_https,
            checks=checks, passed_count=passed, total_count=total, error_message=error_message,
        )
        self.db.add(validation)
        await self.db.commit()
        await self.db.refresh(validation)
        logger.info("site_validation_complete", url=target, passed=passed, total=total)
        return validation

    async def _check_path(self, client: httpx.AsyncClient, base: str, path: str) -> Dict[str, Any]:
        try:
            r = await client.get(urljoin(base.rstrip("/") + "/", path.lstrip("/")))
            return _ok(200 <= r.status_code < 300, f"HTTP {r.status_code}")
        except httpx.HTTPError as exc:
            return _ok(False, f"error: {str(exc)[:80]}")

    async def latest(self, project_id: UUID, tenant_id: UUID) -> Optional[SiteValidation]:
        return (await self.db.execute(
            select(SiteValidation).where(
                SiteValidation.project_id == project_id, SiteValidation.tenant_id == tenant_id
            ).order_by(SiteValidation.created_at.desc()).limit(1)
        )).scalars().first()

    async def list_validations(self, project_id: UUID, tenant_id: UUID, limit: int = 20) -> List[SiteValidation]:
        return list((await self.db.execute(
            select(SiteValidation).where(
                SiteValidation.project_id == project_id, SiteValidation.tenant_id == tenant_id
            ).order_by(SiteValidation.created_at.desc()).limit(limit)
        )).scalars().all())

    async def summary(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        latest = await self.latest(project_id, tenant_id)
        if not latest:
            return {"status": "no_data", "passed": None, "total": None, "checks": {}}
        return {
            "status": "available",
            "url": latest.url,
            "reachable": latest.reachable,
            "http_status": latest.http_status,
            "is_https": latest.is_https,
            "passed": latest.passed_count,
            "total": latest.total_count,
            "checks": latest.checks or {},
            "created_at": latest.created_at.isoformat() if latest.created_at else None,
        }

    @staticmethod
    def _normalize(domain: str) -> str:
        raw = (domain or "").strip()
        if not raw.startswith("http://") and not raw.startswith("https://"):
            raw = "https://" + raw
        parts = urlsplit(raw)
        return f"{parts.scheme}://{parts.netloc}" + (parts.path if parts.path not in ("", "/") else "")
