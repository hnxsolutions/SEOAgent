"""Repository layer for local semantic indexing."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlJob, CrawlPage
from app.models.semantic import (
    SemanticContentType,
    SemanticIndexedContent,
    SemanticIndexRun,
    SemanticIndexStatus,
)

DedupKey = Tuple[UUID, SemanticContentType, int, str]


class SemanticRepository:
    """Database access for semantic indexing jobs and content metadata."""

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

    async def get_page_for_tenant(self, page_id: UUID, tenant_id: UUID) -> Optional[CrawlPage]:
        result = await self.db.execute(
            select(CrawlPage)
            .join(CrawlJob, CrawlJob.id == CrawlPage.crawl_job_id)
            .where(CrawlPage.id == page_id, CrawlJob.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def create_run(
        self,
        crawl: CrawlJob,
        embedding_provider: str,
        embedding_model: str,
        embedding_dimension: int,
        qdrant_collection: str,
    ) -> SemanticIndexRun:
        run = SemanticIndexRun(
            crawl_job_id=crawl.id,
            project_id=crawl.project_id,
            tenant_id=crawl.tenant_id,
            status=SemanticIndexStatus.pending,
            progress=0,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            embedding_dimension=embedding_dimension,
            qdrant_collection=qdrant_collection,
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def get_run(self, run_id: UUID, tenant_id: Optional[UUID] = None) -> Optional[SemanticIndexRun]:
        query = select(SemanticIndexRun).where(SemanticIndexRun.id == run_id)
        if tenant_id:
            query = query.where(SemanticIndexRun.tenant_id == tenant_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def latest_run_for_crawl(
        self,
        crawl_job_id: UUID,
        tenant_id: Optional[UUID] = None,
    ) -> Optional[SemanticIndexRun]:
        query = select(SemanticIndexRun).where(SemanticIndexRun.crawl_job_id == crawl_job_id)
        if tenant_id:
            query = query.where(SemanticIndexRun.tenant_id == tenant_id)
        query = query.order_by(SemanticIndexRun.created_at.desc()).limit(1)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def set_run_status(
        self,
        run: SemanticIndexRun,
        status: SemanticIndexStatus,
        error_message: Optional[str] = None,
        progress: Optional[int] = None,
    ) -> SemanticIndexRun:
        now = datetime.utcnow()
        run.status = status
        run.error_message = error_message
        run.updated_at = now
        if progress is not None:
            run.progress = progress
        if status == SemanticIndexStatus.running and not run.started_at:
            run.started_at = now
        if status in {SemanticIndexStatus.completed, SemanticIndexStatus.failed}:
            run.completed_at = now
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def existing_dedup_keys(
        self,
        crawl_job_id: UUID,
        tenant_id: UUID,
        embedding_model: str,
    ) -> Set[DedupKey]:
        result = await self.db.execute(
            select(
                SemanticIndexedContent.crawl_page_id,
                SemanticIndexedContent.content_type,
                SemanticIndexedContent.chunk_index,
                SemanticIndexedContent.content_hash,
            ).where(
                SemanticIndexedContent.crawl_job_id == crawl_job_id,
                SemanticIndexedContent.tenant_id == tenant_id,
                SemanticIndexedContent.embedding_model == embedding_model,
            )
        )
        return {
            (page_id, content_type, int(chunk_index or 0), content_hash)
            for page_id, content_type, chunk_index, content_hash in result.all()
        }

    async def add_indexed_contents(
        self,
        run: SemanticIndexRun,
        records: Iterable[dict[str, Any]],
    ) -> int:
        count = 0
        for values in records:
            self.db.add(SemanticIndexedContent(**values))
            count += 1
        await self.db.flush()
        return count

    async def finish_run(
        self,
        run: SemanticIndexRun,
        total_pages: int,
        total_vectors: int,
        indexed_vectors: int,
        skipped_duplicates: int,
    ) -> SemanticIndexRun:
        run.total_pages = total_pages
        run.total_vectors = total_vectors
        run.indexed_vectors = indexed_vectors
        run.skipped_duplicates = skipped_duplicates
        run.progress = 100
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def get_primary_page_content(
        self,
        page_id: UUID,
        tenant_id: UUID,
        embedding_model: str,
    ) -> Optional[SemanticIndexedContent]:
        query = (
            select(SemanticIndexedContent)
            .where(
                SemanticIndexedContent.crawl_page_id == page_id,
                SemanticIndexedContent.tenant_id == tenant_id,
                SemanticIndexedContent.embedding_model == embedding_model,
            )
            .order_by(
                (SemanticIndexedContent.content_type == SemanticContentType.full_text).desc(),
                SemanticIndexedContent.indexed_at.desc(),
            )
            .limit(1)
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
