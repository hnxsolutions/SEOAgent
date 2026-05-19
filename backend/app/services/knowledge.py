"""Knowledge base service for local RAG retrieval."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import settings
from app.knowledge.chunking import (
    KnowledgeChunkDocument,
    KnowledgeChunker,
    build_knowledge_vector_payload,
    deterministic_knowledge_point_id,
)
from app.knowledge.qdrant_store import KnowledgeVectorRecord, QdrantKnowledgeStore
from app.models.knowledge import (
    KnowledgeDocumentStatus,
    KnowledgeDocument,
    KnowledgeIndexRun,
    KnowledgeIndexRunStatus,
    KnowledgeSource,
    KnowledgeSourceStatus,
    KnowledgeSourceType,
)
from app.repositories.knowledge import ChunkDedupKey, KnowledgeRepository
from app.semantic.chunking import content_hash, normalize_text
from app.semantic.embeddings import EmbeddingProvider, SentenceTransformerEmbeddingProvider

logger = structlog.get_logger(__name__)


class KnowledgeService:
    """Create, index, and retrieve user-provided knowledge using local components."""

    def __init__(
        self,
        db: AsyncSession,
        embedding_provider: Optional[EmbeddingProvider] = None,
        qdrant_store: Optional[QdrantKnowledgeStore] = None,
        chunker: Optional[KnowledgeChunker] = None,
    ):
        self.db = db
        self.repository = KnowledgeRepository(db)
        self.embedding_provider = embedding_provider or SentenceTransformerEmbeddingProvider(
            settings.SEMANTIC_EMBEDDING_MODEL
        )
        self.qdrant_store = qdrant_store or QdrantKnowledgeStore(
            collection_name=settings.KNOWLEDGE_QDRANT_COLLECTION
        )
        self.chunker = chunker or KnowledgeChunker()

    async def create_source(
        self,
        tenant_id: UUID,
        title: str,
        content: str,
        project_id: Optional[UUID] = None,
        source_type: KnowledgeSourceType = KnowledgeSourceType.manual_note,
        description: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> KnowledgeSource:
        normalized = normalize_text(content)
        if not normalized:
            raise ValueError("Knowledge content cannot be empty")
        source = await self.repository.create_source_with_document(
            tenant_id=tenant_id,
            project_id=project_id,
            source_type=source_type,
            title=normalize_text(title)[:255] or "Untitled knowledge source",
            description=normalize_text(description or "") or None,
            raw_text=content,
            normalized_text=normalized,
            content_hash=content_hash(normalized),
            metadata=metadata or {},
        )
        await self.db.commit()
        await self.db.refresh(source)
        logger.info("Created knowledge source", source_id=str(source.id), tenant_id=str(tenant_id))
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
        return await self.repository.list_sources(
            tenant_id=tenant_id,
            project_id=project_id,
            source_type=source_type,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def get_source(self, source_id: UUID, tenant_id: UUID) -> Optional[KnowledgeSource]:
        return await self.repository.get_source(source_id, tenant_id)

    async def list_documents(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        source_id: Optional[UUID] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[KnowledgeDocument]:
        return await self.repository.list_documents(
            tenant_id=tenant_id,
            project_id=project_id,
            source_id=source_id,
            limit=limit,
            offset=offset,
        )

    async def start_index(self, source_id: UUID, tenant_id: UUID) -> KnowledgeIndexRun:
        source = await self.repository.get_source(source_id, tenant_id)
        if not source:
            raise ValueError("Knowledge source not found")
        documents = await self.repository.list_documents_for_source(source_id, tenant_id)
        if not documents:
            raise ValueError("Knowledge source has no documents")
        run = await self.repository.create_index_run(
            source=source,
            embedding_provider=settings.SEMANTIC_EMBEDDING_PROVIDER,
            embedding_model=self.embedding_provider.model_name,
            embedding_dimension=settings.SEMANTIC_EMBEDDING_DIMENSION,
            qdrant_collection=settings.KNOWLEDGE_QDRANT_COLLECTION,
        )
        await self.repository.set_source_status(source, KnowledgeSourceStatus.indexing)
        await self.db.commit()
        await self.db.refresh(run)
        logger.info("Created knowledge index run", run_id=str(run.id), source_id=str(source_id))
        return run

    async def execute_index(self, run_id: UUID) -> KnowledgeIndexRun:
        run = await self.repository.get_index_run(run_id)
        if not run:
            raise ValueError("Knowledge index run not found")

        await self.repository.set_run_status(run, KnowledgeIndexRunStatus.running, progress=5)
        await self.db.commit()

        try:
            source = await self.repository.get_source(run.source_id, run.tenant_id)
            if not source:
                raise ValueError("Knowledge source not found")
            documents = await self.repository.list_documents_for_source(run.source_id, run.tenant_id)
            existing_keys = await self.repository.existing_chunk_keys(run.tenant_id, run.source_id)
            chunk_documents = [
                chunk
                for document in documents
                for chunk in self.chunker.build_chunks(document, source)
            ]
            chunks_to_index = [
                chunk for chunk in chunk_documents if self._dedup_key(chunk) not in existing_keys
            ]
            skipped_duplicates = len(chunk_documents) - len(chunks_to_index)

            indexed_count = await self._index_chunks(run, chunks_to_index)
            for document in documents:
                await self.repository.set_document_status(document, KnowledgeDocumentStatus.indexed)
            await self.repository.set_source_status(source, KnowledgeSourceStatus.indexed)
            await self.repository.finish_run(
                run,
                documents_processed=len(documents),
                chunks_indexed=indexed_count,
                skipped_duplicates=skipped_duplicates,
            )
            await self.repository.set_run_status(run, KnowledgeIndexRunStatus.completed, progress=100)
            await self.db.commit()
            await self.db.refresh(run)
            logger.info(
                "Completed knowledge index run",
                run_id=str(run.id),
                chunks=indexed_count,
                skipped_duplicates=skipped_duplicates,
            )
            return run
        except Exception as exc:
            source = await self.repository.get_source(run.source_id, run.tenant_id)
            if source:
                await self.repository.set_source_status(source, KnowledgeSourceStatus.failed)
            await self.repository.set_run_status(
                run,
                KnowledgeIndexRunStatus.failed,
                error_message=str(exc),
                progress=100,
            )
            await self.db.commit()
            logger.error("Knowledge indexing failed", run_id=str(run.id), error=str(exc), exc_info=True)
            raise

    async def get_index_status(self, run_id: UUID, tenant_id: UUID) -> Optional[KnowledgeIndexRun]:
        return await self.repository.get_index_run(run_id, tenant_id)

    async def search(
        self,
        tenant_id: UUID,
        query: str,
        project_id: Optional[UUID] = None,
        source_id: Optional[UUID] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        vector = self.embedding_provider.embed_texts([query])[0]
        hits = self.qdrant_store.search(
            vector,
            tenant_id=tenant_id,
            project_id=project_id,
            source_id=source_id,
            limit=limit,
        )
        return [self._format_hit(hit) for hit in hits]

    async def relevant_knowledge(
        self,
        tenant_id: UUID,
        topic: str,
        project_id: Optional[UUID] = None,
        page_id: Optional[UUID] = None,
        limit: int = 8,
    ) -> Dict[str, Any]:
        query_parts = [topic]
        page_context = None
        if page_id:
            page = await self.repository.get_page_context(page_id, tenant_id)
            if page:
                page_context = {
                    "page_id": str(page.id),
                    "url": page.url,
                    "title": page.title,
                    "meta_description": page.meta_description,
                }
                query_parts.extend([
                    page.title or "",
                    page.meta_description or "",
                    normalize_text(page.text_content or "")[:600],
                ])
        query = normalize_text(" ".join(part for part in query_parts if part))
        results = await self.search(tenant_id=tenant_id, project_id=project_id, query=query, limit=limit)
        return {
            "topic": topic,
            "project_id": project_id,
            "page_id": page_id,
            "page_context": page_context,
            "results": results,
            "limit": limit,
        }

    async def _index_chunks(self, run: KnowledgeIndexRun, chunks: Sequence[KnowledgeChunkDocument]) -> int:
        if not chunks:
            return 0

        batch_size = max(1, settings.SEMANTIC_EMBED_BATCH_SIZE)
        indexed_count = 0
        vector_size: Optional[int] = None

        for start in range(0, len(chunks), batch_size):
            batch = list(chunks[start:start + batch_size])
            embeddings = self.embedding_provider.embed_texts([chunk.text for chunk in batch])
            if not embeddings:
                continue
            if vector_size is None:
                vector_size = len(embeddings[0])
                run.embedding_dimension = vector_size
                self.qdrant_store.ensure_collection(vector_size)

            qdrant_records: List[KnowledgeVectorRecord] = []
            db_records: List[dict[str, Any]] = []
            for chunk, vector in zip(batch, embeddings):
                chunk_id = uuid4()
                point_id = deterministic_knowledge_point_id(chunk, run.embedding_model)
                payload = build_knowledge_vector_payload(chunk, run.embedding_model, point_id=point_id)
                payload["chunk_id"] = str(chunk_id)
                qdrant_records.append(KnowledgeVectorRecord(point_id=point_id, vector=vector, payload=payload))
                db_records.append(
                    {
                        "id": chunk_id,
                        "tenant_id": run.tenant_id,
                        "project_id": run.project_id,
                        "document_id": chunk.document_id,
                        "chunk_index": chunk.chunk_index,
                        "chunk_text": chunk.text,
                        "text_preview": chunk.text_preview,
                        "content_hash": chunk.content_hash,
                        "qdrant_point_id": point_id,
                        "metadata_json": payload,
                    }
                )

            self.qdrant_store.upsert_vectors(qdrant_records)
            indexed_count += await self.repository.add_chunks(db_records)
            run.chunks_indexed = indexed_count
            run.progress = min(95, 10 + int((indexed_count / len(chunks)) * 85))
            await self.db.commit()

        return indexed_count

    def _dedup_key(self, chunk: KnowledgeChunkDocument) -> ChunkDedupKey:
        return (chunk.document_id, chunk.chunk_index, chunk.content_hash)

    def _format_hit(self, hit: Dict[str, Any]) -> Dict[str, Any]:
        payload = hit.get("payload") or {}
        return {
            "point_id": hit.get("point_id"),
            "score": hit.get("score"),
            "tenant_id": payload.get("tenant_id"),
            "project_id": payload.get("project_id"),
            "source_id": payload.get("source_id"),
            "document_id": payload.get("document_id"),
            "chunk_id": payload.get("chunk_id"),
            "title": payload.get("title"),
            "source_type": payload.get("source_type"),
            "chunk_index": payload.get("chunk_index"),
            "text_preview": payload.get("text_preview"),
            "chunk_text": payload.get("chunk_text"),
            "metadata": payload.get("metadata") or {},
        }
