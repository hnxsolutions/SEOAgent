"""Service layer for deterministic internal link recommendations."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import settings
from app.internal_links.engine import (
    AuditSignal,
    InternalLinkRulesEngine,
    LinkEdge,
    LinkPage,
    SemanticPair,
)
from app.models.internal_linking import (
    InternalLinkRecommendation,
    InternalLinkRecommendationStatus,
    InternalLinkRecommendationType,
)
from app.repositories.internal_links import InternalLinkRepository
from app.semantic.qdrant_store import QdrantSemanticStore

logger = structlog.get_logger(__name__)


class InternalLinkService:
    """Generate and manage deterministic internal link recommendations."""

    def __init__(
        self,
        db: AsyncSession,
        qdrant_store: Optional[QdrantSemanticStore] = None,
        rules_engine: Optional[InternalLinkRulesEngine] = None,
    ):
        self.db = db
        self.repository = InternalLinkRepository(db)
        self._qdrant_store = qdrant_store
        self.rules_engine = rules_engine or InternalLinkRulesEngine()

    async def generate_for_crawl(
        self,
        crawl_job_id: UUID,
        tenant_id: UUID,
        limit: int = 100,
    ) -> Dict[str, Any]:
        crawl = await self.repository.get_crawl(crawl_job_id, tenant_id)
        if not crawl:
            raise ValueError("Crawl not found")

        pages = await self.repository.list_crawl_pages(crawl_job_id)
        if not pages:
            raise ValueError("Crawl has no pages")

        links = await self.repository.list_crawl_links(crawl_job_id)
        audit_issues = await self.repository.list_audit_issue_signals(crawl_job_id, tenant_id)
        existing_keys = await self.repository.existing_recommendation_keys(crawl_job_id, tenant_id)
        semantic_pairs = await self._semantic_pairs(crawl, pages)

        candidates = self.rules_engine.generate(
            pages=[self._page_snapshot(page) for page in pages],
            links=[self._link_snapshot(link) for link in links],
            audit_signals=[
                AuditSignal(page_id=issue.crawl_page_id, issue_type=issue.issue_type)
                for issue in audit_issues
                if issue.crawl_page_id
            ],
            semantic_pairs=semantic_pairs,
            existing_recommendation_keys=existing_keys,
            limit=limit,
        )

        records = [
            {
                "crawl_job_id": crawl.id,
                "project_id": crawl.project_id,
                "tenant_id": crawl.tenant_id,
                "source_page_id": candidate.source_page_id,
                "source_url": candidate.source_url,
                "target_page_id": candidate.target_page_id,
                "target_url": candidate.target_url,
                "suggested_anchor_text": candidate.suggested_anchor_text,
                "suggested_context_snippet": candidate.suggested_context_snippet,
                "reason": candidate.reason,
                "confidence_score": candidate.confidence_score,
                "priority_score": candidate.priority_score,
                "status": InternalLinkRecommendationStatus.suggested,
                "recommendation_type": candidate.recommendation_type,
                "semantic_similarity": candidate.semantic_similarity,
                "evidence": candidate.evidence,
            }
            for candidate in candidates
        ]
        created_count = await self.repository.add_recommendations(records)
        await self.db.commit()

        recommendations = await self.repository.list_recommendations(
            tenant_id=tenant_id,
            crawl_job_id=crawl_job_id,
            limit=min(limit, max(created_count, 1)),
        )
        logger.info(
            "Generated internal link recommendations",
            crawl_job_id=str(crawl_job_id),
            created_count=created_count,
        )
        return {
            "crawl_id": crawl_job_id,
            "created_count": created_count,
            "recommendations": recommendations,
        }

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
        return await self.repository.list_recommendations(
            tenant_id=tenant_id,
            crawl_job_id=crawl_job_id,
            page_id=page_id,
            status=status,
            recommendation_type=recommendation_type,
            limit=limit,
            offset=offset,
        )

    async def update_status(
        self,
        recommendation_id: UUID,
        tenant_id: UUID,
        status: InternalLinkRecommendationStatus,
    ) -> InternalLinkRecommendation:
        recommendation = await self.repository.get_recommendation(recommendation_id, tenant_id)
        if not recommendation:
            raise ValueError("Recommendation not found")
        recommendation = await self.repository.set_recommendation_status(recommendation, status)
        await self.db.commit()
        await self.db.refresh(recommendation)
        return recommendation

    async def summary(self, crawl_job_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        crawl = await self.repository.get_crawl(crawl_job_id, tenant_id)
        if not crawl:
            raise ValueError("Crawl not found")
        pages = await self.repository.list_crawl_pages(crawl_job_id)
        links = await self.repository.list_crawl_links(crawl_job_id)
        recommendations = await self.repository.list_recommendations(
            tenant_id=tenant_id,
            crawl_job_id=crawl_job_id,
            limit=1000,
        )
        graph_summary = self.rules_engine.summary(
            pages=[self._page_snapshot(page) for page in pages],
            links=[self._link_snapshot(link) for link in links],
            recommendations=recommendations,
        )
        return {
            "crawl_id": crawl_job_id,
            "project_id": crawl.project_id,
            **graph_summary,
            "recommendations_by_status": await self.repository.count_by_status(crawl_job_id, tenant_id),
            "recommendations_by_type": await self.repository.count_by_type(crawl_job_id, tenant_id),
        }

    async def _semantic_pairs(self, crawl, pages) -> List[SemanticPair]:
        primary_contents = await self.repository.list_primary_semantic_contents(
            crawl.id,
            crawl.tenant_id,
            settings.SEMANTIC_EMBEDDING_MODEL,
        )
        page_ids = {page.id for page in pages}
        pairs: List[SemanticPair] = []
        for content in primary_contents:
            hits = self.qdrant_store.similar_to_point(
                content.qdrant_point_id,
                tenant_id=crawl.tenant_id,
                project_id=crawl.project_id,
                crawl_id=crawl.id,
                exclude_page_id=content.crawl_page_id,
                limit=10,
            )
            for hit in hits:
                payload = hit.get("payload") or {}
                target_page_id = self._uuid_or_none(payload.get("page_id"))
                if not target_page_id or target_page_id not in page_ids:
                    continue
                pairs.append(
                    SemanticPair(
                        source_page_id=content.crawl_page_id,
                        target_page_id=target_page_id,
                        similarity=float(hit.get("score") or 0),
                        context_snippet=payload.get("text_preview"),
                    )
                )
        return pairs

    @property
    def qdrant_store(self) -> QdrantSemanticStore:
        if self._qdrant_store is None:
            self._qdrant_store = QdrantSemanticStore(collection_name=settings.SEMANTIC_QDRANT_COLLECTION)
        return self._qdrant_store

    def _page_snapshot(self, page) -> LinkPage:
        h1 = page.h1 or []
        if isinstance(h1, str):
            h1 = [h1]
        return LinkPage(
            id=page.id,
            url=page.url,
            normalized_url=page.normalized_url,
            title=page.title,
            h1=h1,
            word_count=int(page.word_count or 0),
            internal_links=int(page.internal_links or 0),
            depth=int(page.depth or 0),
            text_content=page.text_content,
        )

    def _link_snapshot(self, link) -> LinkEdge:
        return LinkEdge(
            source_page_id=link.source_page_id,
            normalized_url=link.normalized_url,
            link_text=link.link_text,
            link_type=link.link_type or "internal",
        )

    def _uuid_or_none(self, value) -> Optional[UUID]:
        if not value:
            return None
        try:
            return UUID(str(value))
        except (TypeError, ValueError):
            return None
