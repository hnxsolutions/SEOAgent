from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.knowledge.chunking import KnowledgeChunker
from app.models.knowledge import (
    KnowledgeDocumentStatus,
    KnowledgeIndexRunStatus,
    KnowledgeSourceStatus,
    KnowledgeSourceType,
)
from app.services.knowledge import KnowledgeService


class FakeDB:
    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None


class FakeEmbeddingProvider:
    model_name = "local-test-model"

    @property
    def dimension(self):
        return 3

    def embed_texts(self, texts):
        return [[float(index + 1), 0.25, 0.5] for index, _text in enumerate(texts)]


class FakeQdrantStore:
    def __init__(self):
        self.vector_size = None
        self.records = []

    def ensure_collection(self, vector_size):
        self.vector_size = vector_size

    def upsert_vectors(self, records):
        self.records.extend(records)
        return len(records)

    def search(self, query_vector, tenant_id, project_id=None, source_id=None, limit=10):
        return [
            {
                "point_id": "point-1",
                "score": 0.94,
                "payload": {
                    "tenant_id": str(tenant_id),
                    "project_id": str(project_id) if project_id else None,
                    "source_id": str(source_id or uuid4()),
                    "document_id": str(uuid4()),
                    "chunk_id": str(uuid4()),
                    "title": "Business profile",
                    "source_type": "business_profile",
                    "chunk_index": 0,
                    "text_preview": "We provide local SEO and web design services.",
                    "chunk_text": "We provide local SEO and web design services for service businesses.",
                    "metadata": {"audience": "service businesses"},
                },
            }
        ][:limit]


class FakeKnowledgeRepository:
    def __init__(self):
        self.tenant_id = uuid4()
        self.project_id = uuid4()
        self.source_id = uuid4()
        self.document_id = uuid4()
        now = datetime.utcnow()
        self.source = SimpleNamespace(
            id=self.source_id,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            source_type=KnowledgeSourceType.business_profile,
            title="Business profile",
            description="Core services",
            status=KnowledgeSourceStatus.active,
            created_at=now,
            updated_at=now,
        )
        self.document = SimpleNamespace(
            id=self.document_id,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            source_id=self.source_id,
            title="Business profile",
            raw_text="We provide local SEO and web design services for service businesses.",
            normalized_text="We provide local SEO and web design services for service businesses.",
            content_hash="hash",
            metadata_json={"audience": "service businesses"},
            status=KnowledgeDocumentStatus.active,
            created_at=now,
            updated_at=now,
        )
        self.run = SimpleNamespace(
            id=uuid4(),
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            source_id=self.source_id,
            status=KnowledgeIndexRunStatus.pending,
            progress=0,
            embedding_provider="sentence-transformers",
            embedding_model="local-test-model",
            embedding_dimension=3,
            qdrant_collection="seo_knowledge_chunks",
            documents_processed=0,
            chunks_indexed=0,
            skipped_duplicates=0,
            error_message=None,
            started_at=None,
            completed_at=None,
            created_at=now,
            updated_at=now,
        )
        self.created_source_args = None
        self.chunk_records = []
        self.existing_keys = set()

    async def create_source_with_document(self, **kwargs):
        self.created_source_args = kwargs
        self.source.tenant_id = kwargs["tenant_id"]
        self.source.project_id = kwargs["project_id"]
        self.source.source_type = kwargs["source_type"]
        self.source.title = kwargs["title"]
        self.source.description = kwargs["description"]
        self.document.raw_text = kwargs["raw_text"]
        self.document.normalized_text = kwargs["normalized_text"]
        self.document.content_hash = kwargs["content_hash"]
        self.document.metadata_json = kwargs["metadata"]
        return self.source

    async def get_source(self, source_id, tenant_id):
        if source_id == self.source_id and tenant_id == self.tenant_id:
            return self.source
        return None

    async def list_documents_for_source(self, source_id, tenant_id):
        return [self.document] if source_id == self.source_id and tenant_id == self.tenant_id else []

    async def create_index_run(self, source, embedding_provider, embedding_model, embedding_dimension, qdrant_collection):
        self.run.embedding_provider = embedding_provider
        self.run.embedding_model = embedding_model
        self.run.embedding_dimension = embedding_dimension
        self.run.qdrant_collection = qdrant_collection
        return self.run

    async def get_index_run(self, run_id, tenant_id=None):
        return self.run if run_id == self.run.id else None

    async def set_run_status(self, run, status, error_message=None, progress=None):
        run.status = status
        run.error_message = error_message
        if progress is not None:
            run.progress = progress
        return run

    async def set_source_status(self, source, status):
        source.status = status
        return source

    async def set_document_status(self, document, status):
        document.status = status
        return document

    async def existing_chunk_keys(self, tenant_id, source_id):
        return set(self.existing_keys)

    async def add_chunks(self, records):
        records = list(records)
        self.chunk_records.extend(records)
        return len(records)

    async def finish_run(self, run, documents_processed, chunks_indexed, skipped_duplicates):
        run.documents_processed = documents_processed
        run.chunks_indexed = chunks_indexed
        run.skipped_duplicates = skipped_duplicates
        return run

    async def get_page_context(self, page_id, tenant_id):
        return SimpleNamespace(
            id=page_id,
            url="https://example.com/local-seo",
            title="Local SEO Services",
            meta_description="Local SEO for service businesses.",
            text_content="Local SEO pages and technical optimization for service businesses.",
        )


@pytest.mark.asyncio
async def test_knowledge_source_creation_normalizes_and_hashes_content():
    repository = FakeKnowledgeRepository()
    service = KnowledgeService(FakeDB(), embedding_provider=FakeEmbeddingProvider(), qdrant_store=FakeQdrantStore())
    service.repository = repository

    source = await service.create_source(
        tenant_id=repository.tenant_id,
        project_id=repository.project_id,
        source_type=KnowledgeSourceType.business_profile,
        title="  Business profile  ",
        description="  Core services ",
        content="We provide   local SEO.\n\nWe build websites.",
        metadata={"audience": "service businesses"},
    )

    assert source.title == "Business profile"
    assert repository.created_source_args["normalized_text"] == "We provide local SEO. We build websites."
    assert len(repository.created_source_args["content_hash"]) == 64


@pytest.mark.asyncio
async def test_mocked_qdrant_indexing_persists_knowledge_payload():
    repository = FakeKnowledgeRepository()
    qdrant_store = FakeQdrantStore()
    service = KnowledgeService(
        FakeDB(),
        embedding_provider=FakeEmbeddingProvider(),
        qdrant_store=qdrant_store,
        chunker=KnowledgeChunker(max_words=10, overlap_words=2),
    )
    service.repository = repository

    run = await service.execute_index(repository.run.id)

    assert run.status == KnowledgeIndexRunStatus.completed
    assert qdrant_store.vector_size == 3
    assert run.chunks_indexed == len(repository.chunk_records)
    assert qdrant_store.records[0].payload["tenant_id"] == str(repository.tenant_id)
    assert qdrant_store.records[0].payload["source_id"] == str(repository.source_id)
    assert qdrant_store.records[0].payload["content_type"] == "knowledge_chunk"
    assert repository.document.status == KnowledgeDocumentStatus.indexed


@pytest.mark.asyncio
async def test_duplicate_knowledge_chunks_are_skipped():
    repository = FakeKnowledgeRepository()
    service = KnowledgeService(
        FakeDB(),
        embedding_provider=FakeEmbeddingProvider(),
        qdrant_store=FakeQdrantStore(),
        chunker=KnowledgeChunker(max_words=50, overlap_words=0),
    )
    service.repository = repository
    chunk = service.chunker.build_chunks(repository.document, repository.source)[0]
    repository.existing_keys.add(service._dedup_key(chunk))

    run = await service.execute_index(repository.run.id)

    assert run.chunks_indexed == 0
    assert run.skipped_duplicates == 1


@pytest.mark.asyncio
async def test_knowledge_search_and_relevant_retrieval_use_scoped_qdrant_hits():
    repository = FakeKnowledgeRepository()
    service = KnowledgeService(FakeDB(), embedding_provider=FakeEmbeddingProvider(), qdrant_store=FakeQdrantStore())
    service.repository = repository

    results = await service.search(
        tenant_id=repository.tenant_id,
        project_id=repository.project_id,
        source_id=repository.source_id,
        query="local SEO",
        limit=1,
    )
    relevant = await service.relevant_knowledge(
        tenant_id=repository.tenant_id,
        project_id=repository.project_id,
        topic="local SEO services",
        page_id=uuid4(),
        limit=1,
    )

    assert results[0]["score"] == 0.94
    assert results[0]["source_type"] == "business_profile"
    assert relevant["page_context"]["title"] == "Local SEO Services"
    assert relevant["results"][0]["chunk_text"].startswith("We provide local SEO")
