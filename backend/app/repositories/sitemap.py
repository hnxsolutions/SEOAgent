"""Repository layer for sitemap records and sitemap issues."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlJob, CrawlPage
from app.models.sitemap import (
    GSCSitemapRecord,
    SitemapIssue,
    SitemapIssueStatus,
    SitemapSource,
    SitemapStatus,
)


class SitemapRepository:
    """Persistence for sitemap records and their issues."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_sitemaps(self, project_id: UUID, tenant_id: UUID) -> List[GSCSitemapRecord]:
        result = await self.db.execute(
            select(GSCSitemapRecord)
            .where(
                GSCSitemapRecord.project_id == project_id,
                GSCSitemapRecord.tenant_id == tenant_id,
                GSCSitemapRecord.status != SitemapStatus.deleted,
            )
            .order_by(GSCSitemapRecord.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_sitemap(self, sitemap_id: UUID, tenant_id: UUID) -> Optional[GSCSitemapRecord]:
        result = await self.db.execute(
            select(GSCSitemapRecord).where(
                GSCSitemapRecord.id == sitemap_id,
                GSCSitemapRecord.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_url(self, project_id: UUID, tenant_id: UUID, sitemap_url: str) -> Optional[GSCSitemapRecord]:
        result = await self.db.execute(
            select(GSCSitemapRecord).where(
                GSCSitemapRecord.project_id == project_id,
                GSCSitemapRecord.tenant_id == tenant_id,
                GSCSitemapRecord.sitemap_url == sitemap_url,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_sitemap(
        self,
        *,
        project_id: UUID,
        tenant_id: UUID,
        sitemap_url: str,
        values: dict,
    ) -> GSCSitemapRecord:
        record = await self.get_by_url(project_id, tenant_id, sitemap_url)
        if record is None:
            record = GSCSitemapRecord(
                tenant_id=tenant_id,
                project_id=project_id,
                sitemap_url=sitemap_url,
            )
            self.db.add(record)
        for key, value in values.items():
            setattr(record, key, value)
        record.updated_at = datetime.utcnow()
        await self.db.flush()
        return record

    async def mark_deleted(self, record: GSCSitemapRecord) -> GSCSitemapRecord:
        record.status = SitemapStatus.deleted
        record.is_submitted = False
        record.is_pending = False
        record.updated_at = datetime.utcnow()
        await self.db.flush()
        return record

    async def clear_open_issues(self, sitemap_id: UUID) -> None:
        """Remove open (not yet acted-on) issues before a fresh analysis."""
        existing = await self.db.execute(
            select(SitemapIssue).where(
                SitemapIssue.sitemap_id == sitemap_id,
                SitemapIssue.status == SitemapIssueStatus.open,
            )
        )
        for issue in existing.scalars().all():
            await self.db.delete(issue)
        await self.db.flush()

    async def add_issue(self, values: dict) -> SitemapIssue:
        issue = SitemapIssue(**values)
        self.db.add(issue)
        await self.db.flush()
        return issue

    async def list_issues(
        self,
        project_id: UUID,
        tenant_id: UUID,
        *,
        status: Optional[SitemapIssueStatus] = None,
        limit: int = 250,
    ) -> List[SitemapIssue]:
        query = select(SitemapIssue).where(
            SitemapIssue.project_id == project_id,
            SitemapIssue.tenant_id == tenant_id,
        )
        if status is not None:
            query = query.where(SitemapIssue.status == status)
        query = query.order_by(SitemapIssue.severity.desc(), SitemapIssue.created_at.desc()).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def latest_crawl_pages(self, project_id: UUID, tenant_id: UUID) -> dict[str, CrawlPage]:
        """Return the most recent crawl's pages keyed by normalized URL."""
        crawl_result = await self.db.execute(
            select(CrawlJob)
            .where(CrawlJob.project_id == project_id, CrawlJob.tenant_id == tenant_id)
            .order_by(CrawlJob.created_at.desc())
            .limit(1)
        )
        crawl = crawl_result.scalar_one_or_none()
        if not crawl:
            return {}
        pages_result = await self.db.execute(
            select(CrawlPage).where(CrawlPage.crawl_job_id == crawl.id)
        )
        mapping: dict[str, CrawlPage] = {}
        for page in pages_result.scalars().all():
            for key in {page.url, page.normalized_url, page.final_url}:
                if key:
                    mapping[_url_key(key)] = page
        return mapping


def _url_key(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()
