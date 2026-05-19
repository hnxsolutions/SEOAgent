"""Repository layer for deterministic SEO audits."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import (
    SEOAuditRun,
    SEOAuditStatus,
    SEOIssue,
    SEOIssueCategory,
    SEOIssueSeverity,
    SEOIssueStatus,
    SEOPageScore,
)
from app.models.crawl import CrawlJob, CrawlLink, CrawlPage


class AuditRepository:
    """Database access for audit runs, issues, and page scores."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_run(self, crawl: CrawlJob) -> SEOAuditRun:
        run = SEOAuditRun(
            crawl_job_id=crawl.id,
            project_id=crawl.project_id,
            tenant_id=crawl.tenant_id,
            status=SEOAuditStatus.pending,
            progress=0,
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def get_run(
        self,
        audit_run_id: UUID,
        tenant_id: Optional[UUID] = None,
    ) -> Optional[SEOAuditRun]:
        query = select(SEOAuditRun).where(SEOAuditRun.id == audit_run_id)
        if tenant_id:
            query = query.where(SEOAuditRun.tenant_id == tenant_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def latest_run_for_crawl(
        self,
        crawl_job_id: UUID,
        tenant_id: Optional[UUID] = None,
    ) -> Optional[SEOAuditRun]:
        query = select(SEOAuditRun).where(SEOAuditRun.crawl_job_id == crawl_job_id)
        if tenant_id:
            query = query.where(SEOAuditRun.tenant_id == tenant_id)
        query = query.order_by(SEOAuditRun.created_at.desc()).limit(1)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_crawl(
        self,
        crawl_job_id: UUID,
        tenant_id: Optional[UUID] = None,
    ) -> Optional[CrawlJob]:
        query = select(CrawlJob).where(CrawlJob.id == crawl_job_id)
        if tenant_id:
            query = query.where(CrawlJob.tenant_id == tenant_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_crawl_pages(self, crawl_job_id: UUID) -> List[CrawlPage]:
        result = await self.db.execute(
            select(CrawlPage)
            .where(CrawlPage.crawl_job_id == crawl_job_id)
            .order_by(CrawlPage.crawl_order.asc(), CrawlPage.crawled_at.asc())
        )
        return list(result.scalars().all())

    async def list_crawl_links(self, crawl_job_id: UUID) -> List[CrawlLink]:
        result = await self.db.execute(
            select(CrawlLink).where(CrawlLink.crawl_job_id == crawl_job_id)
        )
        return list(result.scalars().all())

    async def set_run_status(
        self,
        run: SEOAuditRun,
        status: SEOAuditStatus,
        error_message: Optional[str] = None,
        progress: Optional[int] = None,
    ) -> SEOAuditRun:
        now = datetime.utcnow()
        run.status = status
        run.error_message = error_message
        run.updated_at = now
        if progress is not None:
            run.progress = progress
        if status == SEOAuditStatus.running and not run.started_at:
            run.started_at = now
        if status in {SEOAuditStatus.completed, SEOAuditStatus.failed}:
            run.completed_at = now
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def replace_results(
        self,
        run: SEOAuditRun,
        issues: List[Dict[str, Any]],
        page_scores: List[Dict[str, Any]],
        site_score: int,
        issue_counts_by_severity: Dict[str, int],
        issue_counts_by_category: Dict[str, int],
    ) -> SEOAuditRun:
        await self.db.execute(delete(SEOIssue).where(SEOIssue.audit_run_id == run.id))
        await self.db.execute(delete(SEOPageScore).where(SEOPageScore.audit_run_id == run.id))

        for issue_values in issues:
            self.db.add(SEOIssue(**issue_values))
        for score_values in page_scores:
            self.db.add(SEOPageScore(**score_values))

        run.site_score = site_score
        run.total_pages = len(page_scores)
        run.total_issues = len(issues)
        run.issue_counts_by_severity = issue_counts_by_severity
        run.issue_counts_by_category = issue_counts_by_category
        run.progress = 100
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def list_issues(
        self,
        tenant_id: UUID,
        audit_run_id: Optional[UUID] = None,
        crawl_job_id: Optional[UUID] = None,
        project_id: Optional[UUID] = None,
        page_id: Optional[UUID] = None,
        severity: Optional[SEOIssueSeverity] = None,
        category: Optional[SEOIssueCategory] = None,
        issue_status: Optional[SEOIssueStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[SEOIssue]:
        query = select(SEOIssue).where(SEOIssue.tenant_id == tenant_id)
        if audit_run_id:
            query = query.where(SEOIssue.audit_run_id == audit_run_id)
        if crawl_job_id:
            query = query.where(SEOIssue.crawl_job_id == crawl_job_id)
        if project_id:
            query = query.where(SEOIssue.project_id == project_id)
        if page_id:
            query = query.where(SEOIssue.crawl_page_id == page_id)
        if severity:
            query = query.where(SEOIssue.severity == severity)
        if category:
            query = query.where(SEOIssue.category == category)
        if issue_status:
            query = query.where(SEOIssue.status == issue_status)
        query = query.order_by(SEOIssue.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_page_score(
        self,
        page_id: UUID,
        tenant_id: UUID,
        audit_run_id: Optional[UUID] = None,
    ) -> Optional[SEOPageScore]:
        query = select(SEOPageScore).where(
            SEOPageScore.crawl_page_id == page_id,
            SEOPageScore.tenant_id == tenant_id,
        )
        if audit_run_id:
            query = query.where(SEOPageScore.audit_run_id == audit_run_id)
        query = query.order_by(SEOPageScore.created_at.desc()).limit(1)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def count_open_issues_by_type(self, run_id: UUID) -> Dict[str, int]:
        result = await self.db.execute(
            select(SEOIssue.issue_type, func.count(SEOIssue.id))
            .where(SEOIssue.audit_run_id == run_id, SEOIssue.status == SEOIssueStatus.open)
            .group_by(SEOIssue.issue_type)
        )
        return {issue_type: int(count) for issue_type, count in result.all()}
