"""One action that submits everything Search Console should receive for a project.

Doing this by hand means four separate calls in a fixed order — detect the
sitemaps, submit each one, start a data sync, then inspect the important URLs —
and getting the order wrong produces errors that look like faults rather than
sequencing mistakes.

**It checks ownership first, on purpose.** Google refuses every write on a
property you are not a verified owner of, with a bare 403 per call. Submitting
blind therefore produced a cascade of identical permission errors and buried the
one fact that mattered: the domain is not verified. One pre-flight check turns
that into a single sentence the operator can act on.

Each step reports its own outcome. A sitemap that Google rejects does not stop
the sync, because the steps are independent and partial progress is worth
keeping.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.search_console import SearchConsoleService
from app.services.sitemap import SitemapIntelligenceService

logger = structlog.get_logger(__name__)

#: Permission levels Google grants that allow writes. Anything else — most
#: commonly `siteUnverifiedUser` — can read nothing and write nothing.
OWNER_PERMISSIONS = {"siteOwner", "siteFullUser"}


class GscSubmitAllService:
    """Runs every Search Console submission a project needs, in order."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.console = SearchConsoleService(db)
        self.sitemaps = SitemapIntelligenceService(db)

    async def run(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        steps: List[Dict[str, Any]] = []

        selection = await self.console.selected_project_property(project_id, tenant_id)
        prop = selection.get("selected_property")
        if not prop:
            return {
                "status": "blocked",
                "reason": "no_property_selected",
                "message": "Choose a Search Console property for this project first.",
                "steps": steps,
            }

        site_url = getattr(prop, "site_url", None) or getattr(prop, "property", None)
        permission = getattr(prop, "permission_level", None)

        # Pre-flight. Without this, every step below fails 403 and the real
        # problem — an unverified domain — is reported four times as a
        # permission error with no mention of verification.
        if permission and permission not in OWNER_PERMISSIONS:
            return {
                "status": "blocked",
                "reason": "not_verified_owner",
                "site_url": site_url,
                "permission_level": permission,
                "message": (
                    f"Google reports your access to {site_url} as '{permission}'. "
                    "Search Console only accepts sitemap submissions and indexing "
                    "requests from a verified owner, so verify the domain in Search "
                    "Console (a DNS TXT record for a domain property) and run this again."
                ),
                "steps": steps,
            }

        steps.append(await self._detect_sitemaps(project_id, tenant_id))
        steps.append(await self._submit_sitemaps(project_id, tenant_id))
        steps.append(await self._start_sync(project_id, tenant_id))

        failed = [s for s in steps if s["status"] == "failed"]
        return {
            "status": "completed" if not failed else "partial",
            "site_url": site_url,
            "permission_level": permission,
            "steps": steps,
        }

    # ------------------------------------------------------------------
    # Steps. Each one reports its own outcome and never raises, so a single
    # rejection does not discard the progress of the others.
    # ------------------------------------------------------------------

    async def _detect_sitemaps(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        try:
            found = await self.sitemaps.detect(project_id, tenant_id)
            return {
                "step": "detect_sitemaps",
                "status": "ok",
                "detail": f"{len(found)} sitemap(s) found",
                "count": len(found),
            }
        except Exception as exc:
            return self._failed("detect_sitemaps", exc)

    async def _submit_sitemaps(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        try:
            known = await self.sitemaps.list_sitemaps(project_id, tenant_id)
        except Exception as exc:
            return self._failed("submit_sitemaps", exc)

        urls = [u for u in {getattr(s, "sitemap_url", None) for s in known} if u]
        if not urls:
            return {
                "step": "submit_sitemaps",
                "status": "skipped",
                "detail": "No sitemap was found to submit. Add one at /sitemap.xml "
                          "or declare it in robots.txt.",
            }

        submitted, errors = [], []
        for url in urls:
            try:
                await self.sitemaps.submit(project_id, tenant_id, url)
                submitted.append(url)
            except Exception as exc:
                errors.append(f"{url}: {exc}")

        if submitted and not errors:
            status = "ok"
        elif submitted:
            status = "partial"
        else:
            status = "failed"

        return {
            "step": "submit_sitemaps",
            "status": status,
            "detail": f"{len(submitted)} submitted"
                      + (f", {len(errors)} rejected" if errors else ""),
            "submitted": submitted,
            "errors": errors[:5],
        }

    async def _start_sync(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        """Import performance data so the opportunity engine has something to read."""
        try:
            job = await self.console.sync_project(tenant_id, project_id)
            return {
                "step": "sync_performance_data",
                "status": "ok",
                "detail": "Search Console sync started",
                "job_id": str(getattr(job, "id", "")) or None,
            }
        except Exception as exc:
            return self._failed("sync_performance_data", exc)

    @staticmethod
    def _failed(step: str, exc: Exception) -> Dict[str, Any]:
        logger.warning("gsc_submit_all_step_failed", step=step, error=str(exc))
        return {"step": step, "status": "failed", "detail": str(exc)[:300]}
