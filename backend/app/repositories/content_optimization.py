"""Repository layer for content optimization suggestions."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import SEOIssue, SEOIssueStatus, SEOPageScore
from app.models.content_optimization import (
    ContentOptimizationRun,
    ContentOptimizationRunStatus,
    ContentOptimizationSuggestion,
    ContentOptimizationSuggestionStatus,
    ContentOptimizationSuggestionType,
)
from app.models.crawl import CrawlJob, CrawlPage
from app.models.internal_linking import InternalLinkRecommendation
from app.models.project import Project

SuggestionKey = Tuple[UUID, ContentOptimizationSuggestionType, str]


class ContentOptimizationRepository:
    """Database access for content optimization runs and suggestions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_crawl(self, crawl_id: UUID, tenant_id: Optional[UUID] = None) -> Optional[CrawlJob]:
        query = select(CrawlJob).where(CrawlJob.id == crawl_id)
        if tenant_id:
            query = query.where(CrawlJob.tenant_id == tenant_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_project(self, project_id: UUID, tenant_id: UUID) -> Optional[Project]:
        result = await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def list_crawl_pages(self, crawl_id: UUID) -> List[CrawlPage]:
        result = await self.db.execute(
            select(CrawlPage)
            .where(CrawlPage.crawl_job_id == crawl_id)
            .order_by(CrawlPage.crawl_order.asc(), CrawlPage.crawled_at.asc())
        )
        return list(result.scalars().all())

    async def list_audit_issues(self, crawl_id: UUID, tenant_id: UUID) -> List[SEOIssue]:
        result = await self.db.execute(
            select(SEOIssue).where(
                SEOIssue.crawl_job_id == crawl_id,
                SEOIssue.tenant_id == tenant_id,
                SEOIssue.status == SEOIssueStatus.open,
                SEOIssue.crawl_page_id.is_not(None),
            )
        )
        return list(result.scalars().all())

    async def list_page_scores(self, crawl_id: UUID, tenant_id: UUID) -> List[SEOPageScore]:
        result = await self.db.execute(
            select(SEOPageScore).where(
                SEOPageScore.crawl_job_id == crawl_id,
                SEOPageScore.tenant_id == tenant_id,
            )
        )
        return list(result.scalars().all())

    async def list_internal_link_recommendations(
        self,
        crawl_id: UUID,
        tenant_id: UUID,
    ) -> List[InternalLinkRecommendation]:
        result = await self.db.execute(
            select(InternalLinkRecommendation).where(
                InternalLinkRecommendation.crawl_job_id == crawl_id,
                InternalLinkRecommendation.tenant_id == tenant_id,
            )
        )
        return list(result.scalars().all())

    async def create_run(self, crawl: CrawlJob, model: str) -> ContentOptimizationRun:
        run = ContentOptimizationRun(
            crawl_id=crawl.id,
            project_id=crawl.project_id,
            tenant_id=crawl.tenant_id,
            status=ContentOptimizationRunStatus.pending,
            progress=0,
            model=model,
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def get_run(
        self,
        run_id: UUID,
        tenant_id: Optional[UUID] = None,
    ) -> Optional[ContentOptimizationRun]:
        query = select(ContentOptimizationRun).where(ContentOptimizationRun.id == run_id)
        if tenant_id:
            query = query.where(ContentOptimizationRun.tenant_id == tenant_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def set_run_status(
        self,
        run: ContentOptimizationRun,
        status: ContentOptimizationRunStatus,
        error_message: Optional[str] = None,
        progress: Optional[int] = None,
    ) -> ContentOptimizationRun:
        now = datetime.utcnow()
        run.status = status
        run.error_message = error_message
        run.updated_at = now
        if progress is not None:
            run.progress = progress
        if status == ContentOptimizationRunStatus.running and not run.started_at:
            run.started_at = now
        if status in {ContentOptimizationRunStatus.completed, ContentOptimizationRunStatus.failed}:
            run.completed_at = now
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def existing_suggestion_keys(self, crawl_id: UUID, tenant_id: UUID) -> Set[SuggestionKey]:
        result = await self.db.execute(
            select(
                ContentOptimizationSuggestion.page_id,
                ContentOptimizationSuggestion.suggestion_type,
                ContentOptimizationSuggestion.content_hash,
            ).where(
                ContentOptimizationSuggestion.crawl_id == crawl_id,
                ContentOptimizationSuggestion.tenant_id == tenant_id,
            )
        )
        return {(page_id, suggestion_type, content_hash) for page_id, suggestion_type, content_hash in result.all()}

    async def add_suggestions(self, records: Iterable[dict]) -> int:
        count = 0
        for values in records:
            self.db.add(ContentOptimizationSuggestion(**values))
            count += 1
        await self.db.flush()
        return count

    async def finish_run(
        self,
        run: ContentOptimizationRun,
        total_pages: int,
        total_suggestions: int,
    ) -> ContentOptimizationRun:
        run.total_pages = total_pages
        run.total_suggestions = total_suggestions
        run.progress = 100
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def list_suggestions(
        self,
        tenant_id: UUID,
        crawl_id: Optional[UUID] = None,
        page_id: Optional[UUID] = None,
        status: Optional[ContentOptimizationSuggestionStatus] = None,
        suggestion_type: Optional[ContentOptimizationSuggestionType] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ContentOptimizationSuggestion]:
        query = select(ContentOptimizationSuggestion).where(ContentOptimizationSuggestion.tenant_id == tenant_id)
        if crawl_id:
            query = query.where(ContentOptimizationSuggestion.crawl_id == crawl_id)
        if page_id:
            query = query.where(ContentOptimizationSuggestion.page_id == page_id)
        if status:
            query = query.where(ContentOptimizationSuggestion.status == status)
        if suggestion_type:
            query = query.where(ContentOptimizationSuggestion.suggestion_type == suggestion_type)
        query = query.order_by(
            ContentOptimizationSuggestion.priority_score.desc(),
            ContentOptimizationSuggestion.confidence_score.desc(),
            ContentOptimizationSuggestion.created_at.desc(),
        ).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_suggestion(
        self,
        suggestion_id: UUID,
        tenant_id: UUID,
    ) -> Optional[ContentOptimizationSuggestion]:
        result = await self.db.execute(
            select(ContentOptimizationSuggestion).where(
                ContentOptimizationSuggestion.id == suggestion_id,
                ContentOptimizationSuggestion.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def set_suggestion_status(
        self,
        suggestion: ContentOptimizationSuggestion,
        status: ContentOptimizationSuggestionStatus,
    ) -> ContentOptimizationSuggestion:
        now = datetime.utcnow()
        suggestion.status = status
        suggestion.updated_at = now
        if status == ContentOptimizationSuggestionStatus.approved:
            suggestion.approved_at = now
        elif status == ContentOptimizationSuggestionStatus.rejected:
            suggestion.rejected_at = now
        elif status == ContentOptimizationSuggestionStatus.applied:
            suggestion.applied_at = now
        await self.db.flush()
        await self.db.refresh(suggestion)
        return suggestion

    async def count_by_status(self, crawl_id: UUID, tenant_id: UUID) -> dict[str, int]:
        result = await self.db.execute(
            select(ContentOptimizationSuggestion.status, func.count(ContentOptimizationSuggestion.id))
            .where(
                ContentOptimizationSuggestion.crawl_id == crawl_id,
                ContentOptimizationSuggestion.tenant_id == tenant_id,
            )
            .group_by(ContentOptimizationSuggestion.status)
        )
        return {status.value if hasattr(status, "value") else str(status): int(count) for status, count in result.all()}

    async def count_by_type(self, crawl_id: UUID, tenant_id: UUID) -> dict[str, int]:
        result = await self.db.execute(
            select(ContentOptimizationSuggestion.suggestion_type, func.count(ContentOptimizationSuggestion.id))
            .where(
                ContentOptimizationSuggestion.crawl_id == crawl_id,
                ContentOptimizationSuggestion.tenant_id == tenant_id,
            )
            .group_by(ContentOptimizationSuggestion.suggestion_type)
        )
        return {suggestion_type.value if hasattr(suggestion_type, "value") else str(suggestion_type): int(count) for suggestion_type, count in result.all()}
