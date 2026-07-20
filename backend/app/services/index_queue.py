"""Auto Index Queue service (official Search Console capabilities only).

Discovers URLs the site owns (from the latest crawl + blog drafts), validates
their indexability locally (HTTP 200, not noindex, self-canonical), lets the
admin approve/reject/schedule them, and — for approved URLs — the ONLY official
submission mechanism: (re)submit the project's sitemap through the Search Console
Sitemaps API. Google offers no official API to request indexing of general web
pages, so this never claims per-URL indexing. Sitemap submission is credential
gated: with no connected Search Console property it degrades gracefully.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blog import BlogDraft
from app.models.crawl import CrawlJob, CrawlPage, CrawlStatus
from app.models.index_queue import IndexUrlSource, IndexUrlStatus, PendingIndexUrl
from app.models.project import Project

logger = structlog.get_logger(__name__)


class IndexQueueService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # -- discovery -----------------------------------------------------------

    async def discover(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        """Discover new URLs from the latest crawl + blog drafts, validate
        indexability, and upsert them into the queue (dedup by url)."""
        project = (await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )).scalars().first()
        if not project:
            raise ValueError("Project not found")

        existing_urls = set((await self.db.execute(
            select(PendingIndexUrl.url).where(PendingIndexUrl.project_id == project_id)
        )).scalars().all())

        added = 0
        candidates = await self._crawl_candidates(project_id, tenant_id)
        candidates += await self._blog_candidates(project_id, tenant_id)

        for url, source, eligible, reason in candidates:
            if not url or url in existing_urls:
                continue
            existing_urls.add(url)
            self.db.add(PendingIndexUrl(
                tenant_id=tenant_id, project_id=project_id, url=url, source=source,
                status=IndexUrlStatus.pending, eligible=eligible, reason=reason,
            ))
            added += 1
        await self.db.commit()
        logger.info("index_queue_discovered", project_id=str(project_id), added=added)
        return {"discovered": added, "total_candidates": len(candidates)}

    async def _crawl_candidates(self, project_id: UUID, tenant_id: UUID):
        run = (await self.db.execute(
            select(CrawlJob).where(
                CrawlJob.project_id == project_id,
                CrawlJob.status == CrawlStatus.completed,
            ).order_by(CrawlJob.created_at.desc()).limit(1)
        )).scalars().first()
        if not run:
            return []
        pages = (await self.db.execute(
            select(CrawlPage).where(CrawlPage.crawl_job_id == run.id).limit(2000)
        )).scalars().all()
        out = []
        for p in pages:
            eligible, reason = self._validate_page(p)
            out.append((p.url, IndexUrlSource.crawl, eligible, reason))
        return out

    @staticmethod
    def _validate_page(page) -> tuple[bool, Optional[str]]:
        """Local indexability validation (no Google call)."""
        status = getattr(page, "status_code", None)
        if status is not None and status != 200:
            return False, f"HTTP {status} (only 200 pages are eligible)"
        if getattr(page, "noindex", False):
            return False, "Page has a noindex directive"
        canonical = getattr(page, "canonical_url_normalized", None)
        normalized = getattr(page, "normalized_url", None) or getattr(page, "url", None)
        if canonical and normalized and canonical.rstrip("/") != normalized.rstrip("/"):
            return False, "Canonical points to a different URL"
        return True, None

    async def _blog_candidates(self, project_id: UUID, tenant_id: UUID):
        drafts = (await self.db.execute(
            select(BlogDraft).where(BlogDraft.project_id == project_id).limit(200)
        )).scalars().all()
        out = []
        for d in drafts:
            base = (getattr(d, "target_site_url", None) or "").rstrip("/")
            slug = getattr(d, "slug", None)
            if base and slug:
                out.append((f"{base}/{slug.lstrip('/')}", IndexUrlSource.blog, True, None))
        return out

    # -- queue management ----------------------------------------------------

    async def list_queue(self, project_id: UUID, tenant_id: UUID, status: Optional[IndexUrlStatus] = None,
                         limit: int = 500) -> List[PendingIndexUrl]:
        query = select(PendingIndexUrl).where(
            PendingIndexUrl.project_id == project_id, PendingIndexUrl.tenant_id == tenant_id
        )
        if status:
            query = query.where(PendingIndexUrl.status == status)
        rows = await self.db.execute(query.order_by(PendingIndexUrl.discovered_at.desc()).limit(limit))
        return list(rows.scalars().all())

    async def summary(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        rows = (await self.db.execute(
            select(PendingIndexUrl.status, func.count(PendingIndexUrl.id))
            .where(PendingIndexUrl.project_id == project_id, PendingIndexUrl.tenant_id == tenant_id)
            .group_by(PendingIndexUrl.status)
        )).all()
        by_status = {self._enum(s): int(c) for s, c in rows}
        return {
            "by_status": by_status,
            "pending": by_status.get("pending", 0),
            "approved": by_status.get("approved", 0),
            "submitted": by_status.get("submitted", 0),
            "indexed": by_status.get("indexed", 0),
            "total": sum(by_status.values()),
        }

    async def set_status(self, url_id: UUID, tenant_id: UUID, status: IndexUrlStatus,
                         scheduled_at: Optional[datetime] = None) -> Optional[PendingIndexUrl]:
        row = (await self.db.execute(
            select(PendingIndexUrl).where(PendingIndexUrl.id == url_id, PendingIndexUrl.tenant_id == tenant_id)
        )).scalars().first()
        if not row:
            return None
        row.status = status
        if status == IndexUrlStatus.approved:
            row.approved_at = datetime.utcnow()
        if status == IndexUrlStatus.scheduled:
            row.scheduled_at = scheduled_at or datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def approve_all(self, project_id: UUID, tenant_id: UUID) -> int:
        rows = (await self.db.execute(
            select(PendingIndexUrl).where(
                PendingIndexUrl.project_id == project_id,
                PendingIndexUrl.tenant_id == tenant_id,
                PendingIndexUrl.status == IndexUrlStatus.pending,
                PendingIndexUrl.eligible.is_(True),
            )
        )).scalars().all()
        now = datetime.utcnow()
        for r in rows:
            r.status = IndexUrlStatus.approved
            r.approved_at = now
        await self.db.commit()
        return len(rows)

    # -- official submission (sitemap resubmission; credential gated) --------

    async def submit_approved(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        """Submit approved URLs the only official way: (re)submit the sitemap via
        the Search Console Sitemaps API. Requires a connected + selected GSC
        property; degrades gracefully otherwise. Never calls a per-URL indexing
        API (Google does not offer one for general pages)."""
        approved = (await self.db.execute(
            select(PendingIndexUrl).where(
                PendingIndexUrl.project_id == project_id,
                PendingIndexUrl.tenant_id == tenant_id,
                PendingIndexUrl.status == IndexUrlStatus.approved,
            )
        )).scalars().all()
        if not approved:
            return {"status": "nothing_to_submit", "submitted": 0,
                    "note": "No approved URLs. Approve URLs first."}

        gsc_note = ("Google offers no official API to request indexing of general "
                    "pages; the official mechanism is sitemap (re)submission.")

        # Official resubmission via the existing sitemap service (project-aware,
        # handles the GSC property + token + client, persists only on API success).
        project = (await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )).scalars().first()
        domain = (getattr(project, "domain", "") or "").rstrip("/")
        if domain and not domain.startswith("http"):
            domain = "https://" + domain
        sitemap_url = f"{domain}/sitemap.xml" if domain else ""
        try:
            from app.services.sitemap import SitemapIntelligenceService

            await SitemapIntelligenceService(self.db).submit(project_id, tenant_id, sitemap_url)
        except Exception as exc:  # graceful — never fabricate a success
            msg = str(exc)
            gated = any(k in msg.lower() for k in ("oauth", "not connected", "disabled", "property", "credential", "token"))
            logger.warning("index_queue_sitemap_submit_failed", error=msg, gated=gated)
            return {
                "status": "not_connected" if gated else "submit_failed",
                "submitted": 0,
                "sitemap_url": sitemap_url,
                "error": msg[:300],
                "note": ("Connect Google Search Console and select a property to submit the sitemap. " + gsc_note)
                if gated else gsc_note,
            }

        now = datetime.utcnow()
        for r in approved:
            r.status = IndexUrlStatus.submitted
            r.submitted_via = "sitemap"
            r.submitted_at = now
        await self.db.commit()
        return {"status": "submitted", "submitted": len(approved), "via": "sitemap", "note": gsc_note}

    @staticmethod
    def _sitemap_url_for(prop) -> str:
        base = str(getattr(prop, "property_url", None) or getattr(prop, "site_url", "")).rstrip("/")
        return f"{base}/sitemap.xml"

    @staticmethod
    def _site_url_for(prop) -> str:
        return str(getattr(prop, "property_url", None) or getattr(prop, "site_url", ""))

    @staticmethod
    def _enum(value):
        return getattr(value, "value", value)
