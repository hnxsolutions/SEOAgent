from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.semantic import SemanticIndexStatus
from app.services.semantic import SemanticService


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
        return [[float(index + 1), 0.0, 0.5] for index, _text in enumerate(texts)]


class FakeQdrantStore:
    def __init__(self):
        self.vector_size = None
        self.records = []

    def ensure_collection(self, vector_size):
        self.vector_size = vector_size

    def upsert_vectors(self, records):
        self.records.extend(records)
        return len(records)

    def search(self, query_vector, tenant_id, project_id=None, limit=10):
        return [
            {
                "point_id": "point-1",
                "score": 0.97,
                "payload": {
                    "tenant_id": str(tenant_id),
                    "project_id": str(project_id) if project_id else None,
                    "crawl_id": str(uuid4()),
                    "page_id": str(uuid4()),
                    "url": "https://example.com",
                    "content_type": "chunk",
                    "heading_context": "Heading",
                    "chunk_index": 0,
                    "text_preview": "Example text",
                },
            }
        ][:limit]


class FakeSemanticRepository:
    def __init__(self):
        self.tenant_id = uuid4()
        self.project_id = uuid4()
        self.crawl_id = uuid4()
        self.page_id = uuid4()
        self.crawl = SimpleNamespace(
            id=self.crawl_id,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
        )
        self.page = SimpleNamespace(
            id=self.page_id,
            url="https://example.com",
            title="Example title",
            meta_description="Example meta description",
            h1=["Example heading"],
            h2=[],
            h3=[],
            h4=[],
            h5=[],
            h6=[],
            text_content="This page has enough content to create semantic documents.",
            crawl_order=1,
            crawled_at=datetime.utcnow(),
        )
        self.run = SimpleNamespace(
            id=uuid4(),
            crawl_job_id=self.crawl_id,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            status=SemanticIndexStatus.pending,
            progress=0,
            embedding_provider="sentence-transformers",
            embedding_model="local-test-model",
            embedding_dimension=3,
            qdrant_collection="test_collection",
            total_pages=0,
            total_vectors=0,
            indexed_vectors=0,
            skipped_duplicates=0,
            error_message=None,
            started_at=None,
            completed_at=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.indexed_contents = []

    async def get_crawl(self, crawl_job_id, tenant_id=None):
        if crawl_job_id == self.crawl_id and (tenant_id is None or tenant_id == self.tenant_id):
            return self.crawl
        return None

    async def list_crawl_pages(self, crawl_job_id):
        return [self.page] if crawl_job_id == self.crawl_id else []

    async def create_run(self, crawl, embedding_provider, embedding_model, embedding_dimension, qdrant_collection):
        self.run.embedding_provider = embedding_provider
        self.run.embedding_model = embedding_model
        self.run.embedding_dimension = embedding_dimension
        self.run.qdrant_collection = qdrant_collection
        return self.run

    async def get_run(self, run_id, tenant_id=None):
        return self.run if run_id == self.run.id else None

    async def set_run_status(self, run, status, error_message=None, progress=None):
        run.status = status
        run.error_message = error_message
        if progress is not None:
            run.progress = progress
        return run

    async def existing_dedup_keys(self, crawl_job_id, tenant_id, embedding_model):
        return set()

    async def finish_run(self, run, total_pages, total_vectors, indexed_vectors, skipped_duplicates):
        run.total_pages = total_pages
        run.total_vectors = total_vectors
        run.indexed_vectors = indexed_vectors
        run.skipped_duplicates = skipped_duplicates
        return run

    async def add_indexed_contents(self, run, records):
        records = list(records)
        self.indexed_contents.extend(records)
        return len(records)


@pytest.mark.asyncio
async def test_semantic_run_creation_uses_local_model_settings():
    repository = FakeSemanticRepository()
    service = SemanticService(FakeDB(), embedding_provider=FakeEmbeddingProvider(), qdrant_store=FakeQdrantStore())
    service.repository = repository

    run = await service.start_index(repository.crawl_id, repository.tenant_id)

    assert run.status == SemanticIndexStatus.pending
    assert run.embedding_model == "local-test-model"
    assert run.qdrant_collection


@pytest.mark.asyncio
async def test_mocked_qdrant_indexing_persists_payload_metadata():
    repository = FakeSemanticRepository()
    qdrant_store = FakeQdrantStore()
    service = SemanticService(FakeDB(), embedding_provider=FakeEmbeddingProvider(), qdrant_store=qdrant_store)
    service.repository = repository

    run = await service.execute_index(repository.run.id)

    assert run.status == SemanticIndexStatus.completed
    assert qdrant_store.vector_size == 3
    assert len(qdrant_store.records) == run.indexed_vectors
    assert run.indexed_vectors == len(repository.indexed_contents)
    first_payload = qdrant_store.records[0].payload
    assert first_payload["tenant_id"] == str(repository.tenant_id)
    assert first_payload["project_id"] == str(repository.project_id)
    assert first_payload["crawl_id"] == str(repository.crawl_id)
    assert first_payload["page_id"] == str(repository.page_id)
    assert first_payload["url"] == "https://example.com"
    assert first_payload["content_type"] in {"full_text", "title", "meta_description", "heading", "chunk"}


@pytest.mark.asyncio
async def test_mocked_qdrant_search_returns_scoped_hits():
    repository = FakeSemanticRepository()
    service = SemanticService(FakeDB(), embedding_provider=FakeEmbeddingProvider(), qdrant_store=FakeQdrantStore())
    service.repository = repository

    results = await service.search(
        tenant_id=repository.tenant_id,
        project_id=repository.project_id,
        query="example",
        limit=1,
    )

    assert results[0]["score"] == 0.97
    assert results[0]["tenant_id"] == str(repository.tenant_id)
    assert results[0]["project_id"] == str(repository.project_id)
    assert results[0]["content_type"] == "chunk"
