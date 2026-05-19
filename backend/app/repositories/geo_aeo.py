"""Repository layer for GEO/AEO scoring and recommendations."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import SEOIssue, SEOIssueStatus, SEOPageScore
from app.models.content_optimization import ContentOptimizationSuggestion
from app.models.crawl import CrawlJob, CrawlLink, CrawlPage
from app.models.geo_aeo import (
    GeoAeoPageScore,
    GeoAeoRecommendation,
    GeoAeoRecommendationStatus,
    GeoAeoRecommendationType,
    GeoAeoRun,
    GeoAeoRunStatus,
)
from app.models.internal_linking import InternalLinkRecommendation
from app.models.semantic import SemanticIndexedContent

RecommendationKey = Tuple[UUID, GeoAeoRecommendationType, str]


class GeoAeoRepository:
    """Database access for GEO/AEO runs, scores, and recommendations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_crawl(self, crawl_id: UUID, tenant_id: Optional[UUID] = None) -> Optional[CrawlJob]:
        query = select(CrawlJob).where(CrawlJob.id == crawl_id)
        if tenant_id:
            query = query.where(CrawlJob.tenant_id == tenant_id)
        result = await self.db.execute(query)
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

    async def list_seo_page_scores(self, crawl_id: UUID, tenant_id: UUID) -> List[SEOPageScore]:
        result = await self.db.execute(
            select(SEOPageScore)
            .where(
                SEOPageScore.crawl_job_id == crawl_id,
                SEOPageScore.tenant_id == tenant_id,
            )
            .order_by(SEOPageScore.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_internal_links(self, crawl_id: UUID) -> List[CrawlLink]:
        result = await self.db.execute(
            select(CrawlLink).where(
                CrawlLink.crawl_job_id == crawl_id,
                CrawlLink.link_type == "internal",
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

    async def list_content_suggestions(self, crawl_id: UUID, tenant_id: UUID) -> List[ContentOptimizationSuggestion]:
        result = await self.db.execute(
            select(ContentOptimizationSuggestion).where(
                ContentOptimizationSuggestion.crawl_id == crawl_id,
                ContentOptimizationSuggestion.tenant_id == tenant_id,
            )
        )
        return list(result.scalars().all())

    async def list_semantic_content(self, crawl_id: UUID, tenant_id: UUID) -> List[SemanticIndexedContent]:
        result = await self.db.execute(
            select(SemanticIndexedContent).where(
                SemanticIndexedContent.crawl_job_id == crawl_id,
                SemanticIndexedContent.tenant_id == tenant_id,
            )
        )
        return list(result.scalars().all())

    async def create_run(self, crawl: CrawlJob, model: str) -> GeoAeoRun:
        run = GeoAeoRun(
            crawl_id=crawl.id,
            project_id=crawl.project_id,
            tenant_id=crawl.tenant_id,
            status=GeoAeoRunStatus.pending,
            progress=0,
            model=model,
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def get_run(self, run_id: UUID, tenant_id: Optional[UUID] = None) -> Optional[GeoAeoRun]:
        query = select(GeoAeoRun).where(GeoAeoRun.id == run_id)
        if tenant_id:
            query = query.where(GeoAeoRun.tenant_id == tenant_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def latest_run_for_crawl(self, crawl_id: UUID, tenant_id: UUID) -> Optional[GeoAeoRun]:
        result = await self.db.execute(
            select(GeoAeoRun)
            .where(GeoAeoRun.crawl_id == crawl_id, GeoAeoRun.tenant_id == tenant_id)
            .order_by(GeoAeoRun.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def set_run_status(
        self,
        run: GeoAeoRun,
        status: GeoAeoRunStatus,
        error_message: Optional[str] = None,
        progress: Optional[int] = None,
    ) -> GeoAeoRun:
        now = datetime.utcnow()
        run.status = status
        run.error_message = error_message
        run.updated_at = now
        if progress is not None:
            run.progress = progress
        if status == GeoAeoRunStatus.running and not run.started_at:
            run.started_at = now
        if status in {GeoAeoRunStatus.completed, GeoAeoRunStatus.failed}:
            run.completed_at = now
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def add_page_scores(self, records: Iterable[dict]) -> int:
        count = 0
        for values in records:
            self.db.add(GeoAeoPageScore(**values))
            count += 1
        await self.db.flush()
        return count

    async def existing_recommendation_keys(self, crawl_id: UUID, tenant_id: UUID) -> Set[RecommendationKey]:
        result = await self.db.execute(
            select(
                GeoAeoRecommendation.page_id,
                GeoAeoRecommendation.recommendation_type,
                GeoAeoRecommendation.content_hash,
            ).where(
                GeoAeoRecommendation.crawl_id == crawl_id,
                GeoAeoRecommendation.tenant_id == tenant_id,
            )
        )
        return {(page_id, rec_type, content_hash) for page_id, rec_type, content_hash in result.all()}

    async def add_recommendations(self, records: Iterable[dict]) -> int:
        count = 0
        for values in records:
            self.db.add(GeoAeoRecommendation(**values))
            count += 1
        await self.db.flush()
        return count

    async def finish_run(
        self,
        run: GeoAeoRun,
        total_pages: int,
        total_recommendations: int,
        average_geo_score: float,
        average_aeo_score: float,
        average_citation_readiness_score: float,
    ) -> GeoAeoRun:
        run.total_pages = total_pages
        run.total_recommendations = total_recommendations
        run.average_geo_score = average_geo_score
        run.average_aeo_score = average_aeo_score
        run.average_citation_readiness_score = average_citation_readiness_score
        run.progress = 100
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def list_page_scores(
        self,
        tenant_id: UUID,
        crawl_id: Optional[UUID] = None,
        page_id: Optional[UUID] = None,
        run_id: Optional[UUID] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> List[GeoAeoPageScore]:
        query = select(GeoAeoPageScore).where(GeoAeoPageScore.tenant_id == tenant_id)
        if crawl_id:
            query = query.where(GeoAeoPageScore.crawl_id == crawl_id)
        if page_id:
            query = query.where(GeoAeoPageScore.page_id == page_id)
        if run_id:
            query = query.where(GeoAeoPageScore.run_id == run_id)
        query = query.order_by(GeoAeoPageScore.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_latest_page_score(self, page_id: UUID, tenant_id: UUID) -> Optional[GeoAeoPageScore]:
        result = await self.db.execute(
            select(GeoAeoPageScore)
            .where(GeoAeoPageScore.page_id == page_id, GeoAeoPageScore.tenant_id == tenant_id)
            .order_by(GeoAeoPageScore.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_recommendations(
        self,
        tenant_id: UUID,
        crawl_id: Optional[UUID] = None,
        page_id: Optional[UUID] = None,
        status: Optional[GeoAeoRecommendationStatus] = None,
        recommendation_type: Optional[GeoAeoRecommendationType] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[GeoAeoRecommendation]:
        query = select(GeoAeoRecommendation).where(GeoAeoRecommendation.tenant_id == tenant_id)
        if crawl_id:
            query = query.where(GeoAeoRecommendation.crawl_id == crawl_id)
        if page_id:
            query = query.where(GeoAeoRecommendation.page_id == page_id)
        if status:
            query = query.where(GeoAeoRecommendation.status == status)
        if recommendation_type:
            query = query.where(GeoAeoRecommendation.recommendation_type == recommendation_type)
        query = query.order_by(
            GeoAeoRecommendation.priority_score.desc(),
            GeoAeoRecommendation.confidence_score.desc(),
            GeoAeoRecommendation.created_at.desc(),
        ).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_recommendation(
        self,
        recommendation_id: UUID,
        tenant_id: UUID,
    ) -> Optional[GeoAeoRecommendation]:
        result = await self.db.execute(
            select(GeoAeoRecommendation).where(
                GeoAeoRecommendation.id == recommendation_id,
                GeoAeoRecommendation.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def set_recommendation_status(
        self,
        recommendation: GeoAeoRecommendation,
        status: GeoAeoRecommendationStatus,
    ) -> GeoAeoRecommendation:
        now = datetime.utcnow()
        recommendation.status = status
        recommendation.updated_at = now
        if status == GeoAeoRecommendationStatus.approved:
            recommendation.approved_at = now
        elif status == GeoAeoRecommendationStatus.rejected:
            recommendation.rejected_at = now
        elif status == GeoAeoRecommendationStatus.applied:
            recommendation.applied_at = now
        await self.db.flush()
        await self.db.refresh(recommendation)
        return recommendation

    async def count_recommendations_by_status(self, crawl_id: UUID, tenant_id: UUID) -> dict[str, int]:
        result = await self.db.execute(
            select(GeoAeoRecommendation.status, func.count(GeoAeoRecommendation.id))
            .where(
                GeoAeoRecommendation.crawl_id == crawl_id,
                GeoAeoRecommendation.tenant_id == tenant_id,
            )
            .group_by(GeoAeoRecommendation.status)
        )
        return {status.value if hasattr(status, "value") else str(status): int(count) for status, count in result.all()}

    async def count_recommendations_by_type(self, crawl_id: UUID, tenant_id: UUID) -> dict[str, int]:
        result = await self.db.execute(
            select(GeoAeoRecommendation.recommendation_type, func.count(GeoAeoRecommendation.id))
            .where(
                GeoAeoRecommendation.crawl_id == crawl_id,
                GeoAeoRecommendation.tenant_id == tenant_id,
            )
            .group_by(GeoAeoRecommendation.recommendation_type)
        )
        return {rec_type.value if hasattr(rec_type, "value") else str(rec_type): int(count) for rec_type, count in result.all()}
