"""Repository layer for user-provided knowledge base content."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlJob, CrawlPage
from app.models.knowledge import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentStatus,
    KnowledgeIndexRun,
    KnowledgeIndexRunStatus,
    KnowledgeSource,
    KnowledgeSourceStatus,
    KnowledgeSourceType,
)

ChunkDedupKey = Tuple[UUID, int, str]


class KnowledgeRepository:
    """Database access for knowledge sources, documents, chunks, and index runs."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_source_with_document(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID],
        source_type: KnowledgeSourceType,
        title: str,
        description: Optional[str],
        raw_text: str,
        normalized_text: str,
        content_hash: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> KnowledgeSource:
        source = KnowledgeSource(
            tenant_id=tenant_id,
            project_id=project_id,
            source_type=source_type,
            title=title,
            description=description,
            status=KnowledgeSourceStatus.active,
        )
        self.db.add(source)
        await self.db.flush()
        document = KnowledgeDocument(
            tenant_id=tenant_id,
            project_id=project_id,
            source_id=source.id,
            title=title,
            raw_text=raw_text,
            normalized_text=normalized_text,
            content_hash=content_hash,
            metadata_json=metadata or {},
            status=KnowledgeDocumentStatus.active,
        )
        self.db.add(document)
        await self.db.flush()
        await self.db.refresh(source)
        return source

    async def list_sources(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        source_type: Optional[KnowledgeSourceType] = None,
        status: Optional[KnowledgeSourceStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[KnowledgeSource]:
        query = select(KnowledgeSource).where(KnowledgeSource.tenant_id == tenant_id)
        if project_id:
            query = query.where(KnowledgeSource.project_id == project_id)
        if source_type:
            query = query.where(KnowledgeSource.source_type == source_type)
        if status:
            query = query.where(KnowledgeSource.status == status)
        query = query.order_by(KnowledgeSource.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_source(self, source_id: UUID, tenant_id: UUID) -> Optional[KnowledgeSource]:
        result = await self.db.execute(
            select(KnowledgeSource).where(
                KnowledgeSource.id == source_id,
                KnowledgeSource.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_documents(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        source_id: Optional[UUID] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[KnowledgeDocument]:
        query = select(KnowledgeDocument).where(KnowledgeDocument.tenant_id == tenant_id)
        if project_id:
            query = query.where(KnowledgeDocument.project_id == project_id)
        if source_id:
            query = query.where(KnowledgeDocument.source_id == source_id)
        query = query.order_by(KnowledgeDocument.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_documents_for_source(self, source_id: UUID, tenant_id: UUID) -> List[KnowledgeDocument]:
        result = await self.db.execute(
            select(KnowledgeDocument)
            .where(
                KnowledgeDocument.source_id == source_id,
                KnowledgeDocument.tenant_id == tenant_id,
                KnowledgeDocument.status != KnowledgeDocumentStatus.archived,
            )
            .order_by(KnowledgeDocument.created_at.asc())
        )
        return list(result.scalars().all())

    async def create_index_run(
        self,
        source: KnowledgeSource,
        embedding_provider: str,
        embedding_model: str,
        embedding_dimension: int,
        qdrant_collection: str,
    ) -> KnowledgeIndexRun:
        run = KnowledgeIndexRun(
            tenant_id=source.tenant_id,
            project_id=source.project_id,
            source_id=source.id,
            status=KnowledgeIndexRunStatus.pending,
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

    async def get_index_run(self, run_id: UUID, tenant_id: Optional[UUID] = None) -> Optional[KnowledgeIndexRun]:
        query = select(KnowledgeIndexRun).where(KnowledgeIndexRun.id == run_id)
        if tenant_id:
            query = query.where(KnowledgeIndexRun.tenant_id == tenant_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def set_run_status(
        self,
        run: KnowledgeIndexRun,
        status: KnowledgeIndexRunStatus,
        error_message: Optional[str] = None,
        progress: Optional[int] = None,
    ) -> KnowledgeIndexRun:
        now = datetime.utcnow()
        run.status = status
        run.error_message = error_message
        run.updated_at = now
        if progress is not None:
            run.progress = progress
        if status == KnowledgeIndexRunStatus.running and not run.started_at:
            run.started_at = now
        if status in {KnowledgeIndexRunStatus.completed, KnowledgeIndexRunStatus.failed}:
            run.completed_at = now
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def set_source_status(self, source: KnowledgeSource, status: KnowledgeSourceStatus) -> KnowledgeSource:
        source.status = status
        source.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(source)
        return source

    async def set_document_status(
        self,
        document: KnowledgeDocument,
        status: KnowledgeDocumentStatus,
    ) -> KnowledgeDocument:
        document.status = status
        document.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(document)
        return document

    async def existing_chunk_keys(self, tenant_id: UUID, source_id: UUID) -> Set[ChunkDedupKey]:
        result = await self.db.execute(
            select(
                KnowledgeChunk.document_id,
                KnowledgeChunk.chunk_index,
                KnowledgeChunk.content_hash,
            )
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(
                KnowledgeChunk.tenant_id == tenant_id,
                KnowledgeDocument.source_id == source_id,
            )
        )
        return {(document_id, int(chunk_index), content_hash) for document_id, chunk_index, content_hash in result.all()}

    async def add_chunks(self, records: Iterable[dict[str, Any]]) -> int:
        count = 0
        for values in records:
            self.db.add(KnowledgeChunk(**values))
            count += 1
        await self.db.flush()
        return count

    async def finish_run(
        self,
        run: KnowledgeIndexRun,
        documents_processed: int,
        chunks_indexed: int,
        skipped_duplicates: int,
    ) -> KnowledgeIndexRun:
        run.documents_processed = documents_processed
        run.chunks_indexed = chunks_indexed
        run.skipped_duplicates = skipped_duplicates
        run.progress = 100
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def get_page_context(self, page_id: UUID, tenant_id: UUID) -> Optional[CrawlPage]:
        result = await self.db.execute(
            select(CrawlPage)
            .join(CrawlJob, CrawlJob.id == CrawlPage.crawl_job_id)
            .where(CrawlPage.id == page_id, CrawlJob.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()
