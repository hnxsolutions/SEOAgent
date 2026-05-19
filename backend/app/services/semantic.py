"""Service layer for local semantic SEO indexing and search."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import settings
from app.models.semantic import (
    SemanticContentType,
    SemanticIndexRun,
    SemanticIndexStatus,
)
from app.repositories.semantic import DedupKey, SemanticRepository
from app.semantic.chunking import (
    SemanticContentChunker,
    SemanticDocument,
    build_vector_payload,
    deterministic_point_id,
)
from app.semantic.embeddings import EmbeddingProvider, SentenceTransformerEmbeddingProvider
from app.semantic.qdrant_store import QdrantSemanticStore, SemanticVectorRecord

logger = structlog.get_logger(__name__)


class SemanticService:
    """Create and query local semantic indexes over crawled content."""

    def __init__(
        self,
        db: AsyncSession,
        embedding_provider: Optional[EmbeddingProvider] = None,
        qdrant_store: Optional[QdrantSemanticStore] = None,
        chunker: Optional[SemanticContentChunker] = None,
    ):
        self.db = db
        self.repository = SemanticRepository(db)
        self.embedding_provider = embedding_provider or SentenceTransformerEmbeddingProvider(
            settings.SEMANTIC_EMBEDDING_MODEL
        )
        self.qdrant_store = qdrant_store or QdrantSemanticStore(
            collection_name=settings.SEMANTIC_QDRANT_COLLECTION
        )
        self.chunker = chunker or SemanticContentChunker()

    async def start_index(self, crawl_job_id: UUID, tenant_id: UUID) -> SemanticIndexRun:
        crawl = await self.repository.get_crawl(crawl_job_id, tenant_id)
        if not crawl:
            raise ValueError("Crawl not found")

        pages = await self.repository.list_crawl_pages(crawl_job_id)
        if not pages:
            raise ValueError("Crawl has no pages to index")

        run = await self.repository.create_run(
            crawl,
            embedding_provider=settings.SEMANTIC_EMBEDDING_PROVIDER,
            embedding_model=self.embedding_provider.model_name,
            embedding_dimension=settings.SEMANTIC_EMBEDDING_DIMENSION,
            qdrant_collection=settings.SEMANTIC_QDRANT_COLLECTION,
        )
        await self.db.commit()
        await self.db.refresh(run)
        logger.info("Created semantic index run", run_id=str(run.id), crawl_job_id=str(crawl_job_id))
        return run

    async def execute_index(self, run_id: UUID) -> SemanticIndexRun:
        run = await self.repository.get_run(run_id)
        if not run:
            raise ValueError("Semantic index run not found")

        await self.repository.set_run_status(run, SemanticIndexStatus.running, progress=5)
        await self.db.commit()

        try:
            crawl = await self.repository.get_crawl(run.crawl_job_id, run.tenant_id)
            if not crawl:
                raise ValueError("Crawl not found")

            pages = await self.repository.list_crawl_pages(run.crawl_job_id)
            documents = [
                document
                for page in pages
                for document in self.chunker.build_page_documents(page, crawl)
            ]
            existing_keys = await self.repository.existing_dedup_keys(
                run.crawl_job_id,
                run.tenant_id,
                run.embedding_model,
            )
            documents_to_index = [
                document for document in documents if self._dedup_key(document) not in existing_keys
            ]
            skipped_duplicates = len(documents) - len(documents_to_index)

            await self.repository.finish_run(
                run,
                total_pages=len(pages),
                total_vectors=len(documents),
                indexed_vectors=0,
                skipped_duplicates=skipped_duplicates,
            )
            await self.db.commit()

            indexed_records = await self._index_documents(run, documents_to_index)
            await self.repository.finish_run(
                run,
                total_pages=len(pages),
                total_vectors=len(documents),
                indexed_vectors=indexed_records,
                skipped_duplicates=skipped_duplicates,
            )
            await self.repository.set_run_status(run, SemanticIndexStatus.completed, progress=100)
            await self.db.commit()
            await self.db.refresh(run)
            logger.info(
                "Completed semantic index run",
                run_id=str(run.id),
                vectors=indexed_records,
                skipped_duplicates=skipped_duplicates,
            )
            return run
        except Exception as exc:
            await self.repository.set_run_status(run, SemanticIndexStatus.failed, error_message=str(exc), progress=100)
            await self.db.commit()
            logger.error("Semantic indexing failed", run_id=str(run.id), error=str(exc), exc_info=True)
            raise

    async def get_index_status(self, run_id: UUID, tenant_id: UUID) -> Optional[SemanticIndexRun]:
        return await self.repository.get_run(run_id, tenant_id)

    async def search(
        self,
        tenant_id: UUID,
        query: str,
        project_id: Optional[UUID] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        vector = self.embedding_provider.embed_texts([query])[0]
        hits = self.qdrant_store.search(vector, tenant_id=tenant_id, project_id=project_id, limit=limit)
        return [self._format_hit(hit) for hit in hits]

    async def similar_pages(
        self,
        page_id: UUID,
        tenant_id: UUID,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        page = await self.repository.get_page_for_tenant(page_id, tenant_id)
        if not page:
            raise ValueError("Page not found")

        primary_content = await self.repository.get_primary_page_content(
            page_id,
            tenant_id,
            self.embedding_provider.model_name,
        )
        if not primary_content:
            return []

        hits = self.qdrant_store.similar_to_point(
            primary_content.qdrant_point_id,
            tenant_id=tenant_id,
            project_id=primary_content.project_id,
            crawl_id=primary_content.crawl_job_id,
            exclude_page_id=page_id,
            limit=limit,
        )
        return [self._format_hit(hit) for hit in hits]

    async def crawl_clusters(
        self,
        crawl_job_id: UUID,
        tenant_id: UUID,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        crawl = await self.repository.get_crawl(crawl_job_id, tenant_id)
        if not crawl:
            raise ValueError("Crawl not found")

        return self.qdrant_store.cluster_crawl(
            tenant_id=tenant_id,
            crawl_id=crawl_job_id,
            project_id=crawl.project_id,
            limit=limit,
        )

    async def _index_documents(self, run: SemanticIndexRun, documents: Sequence[SemanticDocument]) -> int:
        if not documents:
            return 0

        batch_size = max(1, settings.SEMANTIC_EMBED_BATCH_SIZE)
        indexed_count = 0
        vector_size: Optional[int] = None

        for start in range(0, len(documents), batch_size):
            batch = list(documents[start:start + batch_size])
            embeddings = self.embedding_provider.embed_texts([document.text for document in batch])
            if not embeddings:
                continue

            if vector_size is None:
                vector_size = len(embeddings[0])
                run.embedding_dimension = vector_size
                self.qdrant_store.ensure_collection(vector_size)

            qdrant_records: List[SemanticVectorRecord] = []
            db_records: List[dict[str, Any]] = []
            for document, vector in zip(batch, embeddings):
                point_id = deterministic_point_id(document, run.embedding_model)
                payload = build_vector_payload(document, run.embedding_model)
                qdrant_records.append(SemanticVectorRecord(point_id=point_id, vector=vector, payload=payload))
                db_records.append(
                    {
                        "index_run_id": run.id,
                        "crawl_job_id": run.crawl_job_id,
                        "crawl_page_id": document.page_id,
                        "project_id": run.project_id,
                        "tenant_id": run.tenant_id,
                        "content_type": document.content_type,
                        "content_hash": document.content_hash,
                        "embedding_model": run.embedding_model,
                        "embedding_dimension": vector_size,
                        "qdrant_collection": run.qdrant_collection,
                        "qdrant_point_id": point_id,
                        "url": document.url,
                        "heading_context": document.heading_context,
                        "chunk_index": document.chunk_index,
                        "text_preview": document.text_preview,
                    }
                )

            self.qdrant_store.upsert_vectors(qdrant_records)
            indexed_count += await self.repository.add_indexed_contents(run, db_records)
            run.indexed_vectors = indexed_count
            run.progress = min(95, 10 + int((indexed_count / len(documents)) * 85))
            await self.db.commit()

        return indexed_count

    def _dedup_key(self, document: SemanticDocument) -> DedupKey:
        return (
            document.page_id,
            document.content_type,
            document.chunk_index,
            document.content_hash,
        )

    def _format_hit(self, hit: Dict[str, Any]) -> Dict[str, Any]:
        payload = hit.get("payload") or {}
        return {
            "point_id": hit.get("point_id"),
            "score": hit.get("score"),
            "tenant_id": payload.get("tenant_id"),
            "project_id": payload.get("project_id"),
            "crawl_id": payload.get("crawl_id"),
            "page_id": payload.get("page_id"),
            "url": payload.get("url"),
            "content_type": payload.get("content_type"),
            "heading_context": payload.get("heading_context"),
            "chunk_index": payload.get("chunk_index"),
            "text_preview": payload.get("text_preview"),
        }
