"""Repository layer for blog plans, topics, and drafts."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional, Set
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import SEOIssue, SEOIssueStatus
from app.models.blog import BlogDraft, BlogDraftStatus, BlogPlan, BlogPlanStatus, BlogTopic, BlogTopicStatus
from app.models.content_optimization import ContentOptimizationSuggestion
from app.models.crawl import CrawlJob, CrawlPage, CrawlStatus
from app.models.geo_aeo import GeoAeoPageScore, GeoAeoRecommendation
from app.models.internal_linking import InternalLinkRecommendation
from app.models.semantic import SemanticIndexedContent


class BlogRepository:
    """Persistence and signal access for blog planning workflows."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_plan(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID],
        title: str,
        description: Optional[str],
        target_site_url: Optional[str],
        blogs_per_week: int,
    ) -> BlogPlan:
        plan = BlogPlan(
            tenant_id=tenant_id,
            project_id=project_id,
            title=title,
            description=description,
            target_site_url=target_site_url,
            status=BlogPlanStatus.draft,
            blogs_per_week=blogs_per_week,
        )
        self.db.add(plan)
        await self.db.flush()
        await self.db.refresh(plan)
        return plan

    async def list_plans(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        status: Optional[BlogPlanStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[BlogPlan]:
        query = select(BlogPlan).where(BlogPlan.tenant_id == tenant_id)
        if project_id:
            query = query.where(BlogPlan.project_id == project_id)
        if status:
            query = query.where(BlogPlan.status == status)
        query = query.order_by(BlogPlan.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_plan(self, plan_id: UUID, tenant_id: UUID) -> Optional[BlogPlan]:
        result = await self.db.execute(
            select(BlogPlan).where(BlogPlan.id == plan_id, BlogPlan.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def set_plan_status(self, plan: BlogPlan, status: BlogPlanStatus) -> BlogPlan:
        plan.status = status
        plan.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(plan)
        return plan

    async def existing_topic_keywords(self, plan_id: UUID, tenant_id: UUID) -> Set[str]:
        result = await self.db.execute(
            select(BlogTopic.target_keyword).where(
                BlogTopic.blog_plan_id == plan_id,
                BlogTopic.tenant_id == tenant_id,
            )
        )
        return {self._keyword_key(keyword) for keyword in result.scalars().all()}

    async def add_topics(self, records: Iterable[dict]) -> int:
        count = 0
        for values in records:
            self.db.add(BlogTopic(**values))
            count += 1
        await self.db.flush()
        return count

    async def list_topics(
        self,
        plan_id: UUID,
        tenant_id: UUID,
        status: Optional[BlogTopicStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[BlogTopic]:
        query = select(BlogTopic).where(BlogTopic.blog_plan_id == plan_id, BlogTopic.tenant_id == tenant_id)
        if status:
            query = query.where(BlogTopic.status == status)
        query = query.order_by(BlogTopic.priority_score.desc(), BlogTopic.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_topic(self, topic_id: UUID, tenant_id: UUID) -> Optional[BlogTopic]:
        result = await self.db.execute(
            select(BlogTopic).where(BlogTopic.id == topic_id, BlogTopic.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def set_topic_status(self, topic: BlogTopic, status: BlogTopicStatus) -> BlogTopic:
        now = datetime.utcnow()
        topic.status = status
        topic.updated_at = now
        if status == BlogTopicStatus.approved:
            topic.approved_at = now
        elif status == BlogTopicStatus.rejected:
            topic.rejected_at = now
        elif status == BlogTopicStatus.drafted:
            topic.drafted_at = now
        elif status == BlogTopicStatus.published:
            topic.published_at = now
        await self.db.flush()
        await self.db.refresh(topic)
        return topic

    async def create_draft(self, values: dict) -> BlogDraft:
        draft = BlogDraft(**values)
        self.db.add(draft)
        await self.db.flush()
        await self.db.refresh(draft)
        return draft

    async def get_draft(self, draft_id: UUID, tenant_id: UUID) -> Optional[BlogDraft]:
        result = await self.db.execute(
            select(BlogDraft).where(BlogDraft.id == draft_id, BlogDraft.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def list_drafts_for_plan(
        self,
        plan_id: UUID,
        tenant_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> List[BlogDraft]:
        query = (
            select(BlogDraft)
            .join(BlogTopic, BlogTopic.id == BlogDraft.blog_topic_id)
            .where(BlogTopic.blog_plan_id == plan_id, BlogDraft.tenant_id == tenant_id)
            .order_by(BlogDraft.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_candidate_pages(self, plan: BlogPlan, limit: int = 50) -> List[CrawlPage]:
        query = (
            select(CrawlPage)
            .join(CrawlJob, CrawlJob.id == CrawlPage.crawl_job_id)
            .where(CrawlJob.tenant_id == plan.tenant_id, CrawlJob.status == CrawlStatus.completed)
        )
        if plan.project_id:
            query = query.where(CrawlJob.project_id == plan.project_id)
        host = self._host(plan.target_site_url)
        if host:
            query = query.where(CrawlPage.url.ilike(f"%{host}%"))
        query = query.order_by(CrawlPage.word_count.desc(), CrawlPage.crawled_at.desc()).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_audit_issues_for_pages(self, tenant_id: UUID, page_ids: List[UUID]) -> List[SEOIssue]:
        if not page_ids:
            return []
        result = await self.db.execute(
            select(SEOIssue).where(
                SEOIssue.tenant_id == tenant_id,
                SEOIssue.status == SEOIssueStatus.open,
                SEOIssue.crawl_page_id.in_(page_ids),
            )
        )
        return list(result.scalars().all())

    async def list_geo_scores_for_pages(self, tenant_id: UUID, page_ids: List[UUID]) -> List[GeoAeoPageScore]:
        if not page_ids:
            return []
        result = await self.db.execute(
            select(GeoAeoPageScore)
            .where(GeoAeoPageScore.tenant_id == tenant_id, GeoAeoPageScore.page_id.in_(page_ids))
            .order_by(GeoAeoPageScore.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_geo_recommendations_for_pages(self, tenant_id: UUID, page_ids: List[UUID]) -> List[GeoAeoRecommendation]:
        if not page_ids:
            return []
        result = await self.db.execute(
            select(GeoAeoRecommendation)
            .where(GeoAeoRecommendation.tenant_id == tenant_id, GeoAeoRecommendation.page_id.in_(page_ids))
            .order_by(GeoAeoRecommendation.priority_score.desc())
        )
        return list(result.scalars().all())

    async def list_content_suggestions_for_pages(
        self,
        tenant_id: UUID,
        page_ids: List[UUID],
    ) -> List[ContentOptimizationSuggestion]:
        if not page_ids:
            return []
        result = await self.db.execute(
            select(ContentOptimizationSuggestion)
            .where(ContentOptimizationSuggestion.tenant_id == tenant_id, ContentOptimizationSuggestion.page_id.in_(page_ids))
            .order_by(ContentOptimizationSuggestion.priority_score.desc())
        )
        return list(result.scalars().all())

    async def list_internal_link_recommendations_for_pages(
        self,
        tenant_id: UUID,
        page_ids: List[UUID],
    ) -> List[InternalLinkRecommendation]:
        if not page_ids:
            return []
        result = await self.db.execute(
            select(InternalLinkRecommendation)
            .where(
                InternalLinkRecommendation.tenant_id == tenant_id,
                (
                    InternalLinkRecommendation.source_page_id.in_(page_ids)
                    | InternalLinkRecommendation.target_page_id.in_(page_ids)
                ),
            )
            .order_by(InternalLinkRecommendation.priority_score.desc())
        )
        return list(result.scalars().all())

    async def list_semantic_content_for_pages(self, tenant_id: UUID, page_ids: List[UUID]) -> List[SemanticIndexedContent]:
        if not page_ids:
            return []
        result = await self.db.execute(
            select(SemanticIndexedContent).where(
                SemanticIndexedContent.tenant_id == tenant_id,
                SemanticIndexedContent.crawl_page_id.in_(page_ids),
            )
        )
        return list(result.scalars().all())

    def _keyword_key(self, value: str) -> str:
        return " ".join((value or "").lower().split())

    def _host(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        parsed = urlparse(url if "://" in url else f"https://{url}")
        return parsed.netloc.lower().removeprefix("www.") or None
