"""Repository layer for internal link recommendations."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import SEOIssue, SEOIssueStatus
from app.models.crawl import CrawlJob, CrawlLink, CrawlPage
from app.models.internal_linking import (
    InternalLinkRecommendation,
    InternalLinkRecommendationStatus,
    InternalLinkRecommendationType,
)
from app.models.semantic import SemanticContentType, SemanticIndexedContent

RecommendationKey = Tuple[UUID, UUID, InternalLinkRecommendationType]


class InternalLinkRepository:
    """Database access for crawl graph and recommendations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_crawl(self, crawl_job_id: UUID, tenant_id: Optional[UUID] = None) -> Optional[CrawlJob]:
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

    async def list_audit_issue_signals(self, crawl_job_id: UUID, tenant_id: UUID) -> List[SEOIssue]:
        result = await self.db.execute(
            select(SEOIssue).where(
                SEOIssue.crawl_job_id == crawl_job_id,
                SEOIssue.tenant_id == tenant_id,
                SEOIssue.status == SEOIssueStatus.open,
                SEOIssue.crawl_page_id.is_not(None),
            )
        )
        return list(result.scalars().all())

    async def list_primary_semantic_contents(
        self,
        crawl_job_id: UUID,
        tenant_id: UUID,
        embedding_model: str,
    ) -> List[SemanticIndexedContent]:
        result = await self.db.execute(
            select(SemanticIndexedContent)
            .where(
                SemanticIndexedContent.crawl_job_id == crawl_job_id,
                SemanticIndexedContent.tenant_id == tenant_id,
                SemanticIndexedContent.embedding_model == embedding_model,
                SemanticIndexedContent.content_type == SemanticContentType.full_text,
            )
            .order_by(SemanticIndexedContent.indexed_at.desc())
        )
        contents_by_page = {}
        for content in result.scalars().all():
            contents_by_page.setdefault(content.crawl_page_id, content)
        return list(contents_by_page.values())

    async def existing_recommendation_keys(self, crawl_job_id: UUID, tenant_id: UUID) -> Set[RecommendationKey]:
        result = await self.db.execute(
            select(
                InternalLinkRecommendation.source_page_id,
                InternalLinkRecommendation.target_page_id,
                InternalLinkRecommendation.recommendation_type,
            ).where(
                InternalLinkRecommendation.crawl_job_id == crawl_job_id,
                InternalLinkRecommendation.tenant_id == tenant_id,
            )
        )
        return {(source_id, target_id, rec_type) for source_id, target_id, rec_type in result.all()}

    async def add_recommendations(self, records: Iterable[dict]) -> int:
        count = 0
        for values in records:
            self.db.add(InternalLinkRecommendation(**values))
            count += 1
        await self.db.flush()
        return count

    async def list_recommendations(
        self,
        tenant_id: UUID,
        crawl_job_id: Optional[UUID] = None,
        page_id: Optional[UUID] = None,
        status: Optional[InternalLinkRecommendationStatus] = None,
        recommendation_type: Optional[InternalLinkRecommendationType] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[InternalLinkRecommendation]:
        query = select(InternalLinkRecommendation).where(InternalLinkRecommendation.tenant_id == tenant_id)
        if crawl_job_id:
            query = query.where(InternalLinkRecommendation.crawl_job_id == crawl_job_id)
        if page_id:
            query = query.where(
                (InternalLinkRecommendation.source_page_id == page_id)
                | (InternalLinkRecommendation.target_page_id == page_id)
            )
        if status:
            query = query.where(InternalLinkRecommendation.status == status)
        if recommendation_type:
            query = query.where(InternalLinkRecommendation.recommendation_type == recommendation_type)
        query = query.order_by(
            InternalLinkRecommendation.priority_score.desc(),
            InternalLinkRecommendation.confidence_score.desc(),
            InternalLinkRecommendation.created_at.desc(),
        ).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_recommendation(
        self,
        recommendation_id: UUID,
        tenant_id: UUID,
    ) -> Optional[InternalLinkRecommendation]:
        result = await self.db.execute(
            select(InternalLinkRecommendation).where(
                InternalLinkRecommendation.id == recommendation_id,
                InternalLinkRecommendation.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def set_recommendation_status(
        self,
        recommendation: InternalLinkRecommendation,
        status: InternalLinkRecommendationStatus,
    ) -> InternalLinkRecommendation:
        now = datetime.utcnow()
        recommendation.status = status
        recommendation.updated_at = now
        if status == InternalLinkRecommendationStatus.approved:
            recommendation.approved_at = now
        elif status == InternalLinkRecommendationStatus.rejected:
            recommendation.rejected_at = now
        elif status == InternalLinkRecommendationStatus.applied:
            recommendation.applied_at = now
        await self.db.flush()
        await self.db.refresh(recommendation)
        return recommendation

    async def count_by_status(self, crawl_job_id: UUID, tenant_id: UUID) -> dict[str, int]:
        result = await self.db.execute(
            select(InternalLinkRecommendation.status, func.count(InternalLinkRecommendation.id))
            .where(
                InternalLinkRecommendation.crawl_job_id == crawl_job_id,
                InternalLinkRecommendation.tenant_id == tenant_id,
            )
            .group_by(InternalLinkRecommendation.status)
        )
        return {status.value if hasattr(status, "value") else str(status): int(count) for status, count in result.all()}

    async def count_by_type(self, crawl_job_id: UUID, tenant_id: UUID) -> dict[str, int]:
        result = await self.db.execute(
            select(InternalLinkRecommendation.recommendation_type, func.count(InternalLinkRecommendation.id))
            .where(
                InternalLinkRecommendation.crawl_job_id == crawl_job_id,
                InternalLinkRecommendation.tenant_id == tenant_id,
            )
            .group_by(InternalLinkRecommendation.recommendation_type)
        )
        return {rec_type.value if hasattr(rec_type, "value") else str(rec_type): int(count) for rec_type, count in result.all()}
