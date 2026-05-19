"""
Repository layer for crawl persistence.

Services and workers use this module for database access so API routing and
crawler execution stay focused on orchestration.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.url_utils import URLNormalizer
from app.models.crawl import CrawlError, CrawlJob, CrawlLink, CrawlPage, CrawlStatus


class CrawlRepository:
    """Persistence operations for crawl jobs, pages, links, and errors."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_job(self, **values: Any) -> CrawlJob:
        job = CrawlJob(**values)
        self.db.add(job)
        await self.db.flush()
        await self.db.refresh(job)
        return job

    async def get_job(
        self,
        job_id: UUID,
        tenant_id: Optional[UUID] = None,
    ) -> Optional[CrawlJob]:
        query = select(CrawlJob).where(CrawlJob.id == job_id)
        if tenant_id:
            query = query.where(CrawlJob.tenant_id == tenant_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_jobs(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        status: Optional[CrawlStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CrawlJob]:
        query = select(CrawlJob).where(CrawlJob.tenant_id == tenant_id)
        if project_id:
            query = query.where(CrawlJob.project_id == project_id)
        if status:
            query = query.where(CrawlJob.status == status)
        query = query.order_by(CrawlJob.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_jobs(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        status: Optional[CrawlStatus] = None,
    ) -> int:
        query = select(func.count(CrawlJob.id)).where(CrawlJob.tenant_id == tenant_id)
        if project_id:
            query = query.where(CrawlJob.project_id == project_id)
        if status:
            query = query.where(CrawlJob.status == status)
        result = await self.db.execute(query)
        return int(result.scalar_one() or 0)

    async def set_job_status(
        self,
        job: CrawlJob,
        status: CrawlStatus,
        error_message: Optional[str] = None,
        worker_id: Optional[str] = None,
    ) -> CrawlJob:
        now = datetime.utcnow()
        job.status = status
        job.error_message = error_message
        job.worker_id = worker_id or job.worker_id
        job.updated_at = now

        if status == CrawlStatus.running and not job.started_at:
            job.started_at = now
        if status in {CrawlStatus.completed, CrawlStatus.failed, CrawlStatus.cancelled}:
            job.completed_at = now
        if status == CrawlStatus.completed:
            job.progress = 100
        if error_message:
            job.last_error_at = now

        await self.db.flush()
        await self.db.refresh(job)
        return job

    async def save_page(
        self,
        job_id: UUID,
        page_data: Dict[str, Any],
        crawl_order: int = 0,
        depth: int = 0,
        retry_count: int = 0,
    ) -> CrawlPage:
        url = page_data.get("url")
        normalized_url = page_data.get("normalized_url") or URLNormalizer.normalize_url(url or "")

        query = select(CrawlPage).where(CrawlPage.crawl_job_id == job_id)
        if normalized_url:
            query = query.where(CrawlPage.normalized_url == normalized_url)
        else:
            query = query.where(CrawlPage.url == url)

        result = await self.db.execute(query)
        page = result.scalar_one_or_none()

        if page is None:
            page = CrawlPage(crawl_job_id=job_id, url=url, normalized_url=normalized_url)
            self.db.add(page)

        for key, value in page_data.items():
            if hasattr(page, key):
                setattr(page, key, value)

        page.normalized_url = normalized_url
        page.crawl_order = crawl_order
        page.depth = depth
        page.retry_count = retry_count
        page.crawled_at = datetime.utcnow()

        await self.db.flush()
        await self.db.refresh(page)
        return page

    async def replace_page_links(
        self,
        job_id: UUID,
        source_page_id: UUID,
        internal_links: List[Dict[str, Any]],
        external_links: List[Dict[str, Any]],
    ) -> None:
        await self.db.execute(delete(CrawlLink).where(CrawlLink.source_page_id == source_page_id))

        for link_type, links in (("internal", internal_links), ("external", external_links)):
            for link_data in links:
                link = CrawlLink(
                    crawl_job_id=job_id,
                    source_page_id=source_page_id,
                    url=link_data.get("url"),
                    normalized_url=link_data.get("normalized_url"),
                    link_text=link_data.get("text"),
                    link_type=link_type,
                    rel_attribute=link_data.get("rel"),
                    is_nofollow=link_data.get("is_nofollow", False),
                    is_sponsored=link_data.get("is_sponsored", False),
                    is_ugc=link_data.get("is_ugc", False),
                    target_attribute=link_data.get("target"),
                    status_code=link_data.get("status_code"),
                    is_broken=link_data.get("is_broken", False),
                    response_time_ms=link_data.get("response_time_ms"),
                )
                self.db.add(link)

        await self.db.flush()

    async def save_error(
        self,
        job_id: UUID,
        error_type: str,
        error_message: str,
        url: Optional[str] = None,
        page_id: Optional[UUID] = None,
        error_code: Optional[str] = None,
        retry_count: int = 0,
        stack_trace: Optional[str] = None,
    ) -> CrawlError:
        error = CrawlError(
            crawl_job_id=job_id,
            error_type=error_type,
            error_message=error_message,
            url=url,
            page_id=page_id,
            error_code=error_code,
            retry_count=retry_count,
            stack_trace=stack_trace,
        )
        self.db.add(error)
        await self.db.flush()
        await self.db.refresh(error)
        return error

    async def list_pages(
        self,
        job_id: UUID,
        limit: int = 100,
        offset: int = 0,
        status_code: Optional[int] = None,
        has_issues: bool = False,
    ) -> List[CrawlPage]:
        query = select(CrawlPage).where(CrawlPage.crawl_job_id == job_id)
        if status_code is not None:
            query = query.where(CrawlPage.status_code == status_code)
        if has_issues:
            query = query.where(CrawlPage.issue_count > 0)
        query = query.order_by(CrawlPage.crawled_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_errors(
        self,
        job_id: UUID,
        error_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[CrawlError]:
        query = select(CrawlError).where(CrawlError.crawl_job_id == job_id)
        if error_type:
            query = query.where(CrawlError.error_type == error_type)
        query = query.order_by(CrawlError.created_at.desc()).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_links(
        self,
        job_id: UUID,
        link_type: Optional[str] = None,
        is_broken: bool = False,
        limit: int = 100,
    ) -> List[CrawlLink]:
        query = select(CrawlLink).where(CrawlLink.crawl_job_id == job_id)
        if link_type:
            query = query.where(CrawlLink.link_type == link_type)
        if is_broken:
            query = query.where(CrawlLink.is_broken.is_(True))
        query = query.limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def refresh_job_aggregates(self, job_id: UUID) -> Optional[CrawlJob]:
        job = await self.get_job(job_id)
        if not job:
            return None

        page_count = await self.db.execute(
            select(func.count(CrawlPage.id)).where(CrawlPage.crawl_job_id == job_id)
        )
        failed_count = await self.db.execute(
            select(func.count(CrawlPage.id)).where(
                CrawlPage.crawl_job_id == job_id,
                CrawlPage.status_code.is_(None),
            )
        )
        link_sums = await self.db.execute(
            select(
                func.coalesce(func.sum(CrawlPage.internal_links), 0),
                func.coalesce(func.sum(CrawlPage.external_links), 0),
                func.coalesce(func.sum(CrawlPage.issue_count), 0),
            ).where(CrawlPage.crawl_job_id == job_id)
        )

        internal_links, external_links, issues = link_sums.one()
        total_pages = int(page_count.scalar() or 0)

        job.total_pages_crawled = total_pages
        job.total_pages_failed = int(failed_count.scalar() or 0)
        job.total_internal_links = int(internal_links or 0)
        job.total_external_links = int(external_links or 0)
        job.total_issues_found = int(issues or 0)
        job.progress = min(100, int((total_pages / max(job.max_pages, 1)) * 100))
        job.updated_at = datetime.utcnow()

        await self.db.flush()
        await self.db.refresh(job)
        return job
