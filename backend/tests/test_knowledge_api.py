from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import knowledge as knowledge_routes


def make_source(source_id, tenant_id, project_id=None):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=source_id,
        tenant_id=tenant_id,
        project_id=project_id,
        source_type="manual_note",
        title="Business profile",
        description="Core services",
        status="active",
        created_at=now,
        updated_at=now,
    )


def make_document(source_id, tenant_id, project_id=None):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        source_id=source_id,
        title="Business profile",
        raw_text="We provide local SEO.",
        normalized_text="We provide local SEO.",
        content_hash="a" * 64,
        metadata_json={"audience": "service businesses"},
        status="active",
        created_at=now,
        updated_at=now,
    )


def make_run(source_id, tenant_id, project_id=None):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        source_id=source_id,
        status="pending",
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


def make_search_result(tenant_id, project_id, source_id):
    return {
        "point_id": "point-1",
        "score": 0.93,
        "tenant_id": str(tenant_id),
        "project_id": str(project_id) if project_id else None,
        "source_id": str(source_id),
        "document_id": str(uuid4()),
        "chunk_id": str(uuid4()),
        "title": "Business profile",
        "source_type": "manual_note",
        "chunk_index": 0,
        "text_preview": "We provide local SEO.",
        "chunk_text": "We provide local SEO and landing page strategy.",
        "metadata": {"audience": "service businesses"},
    }


def test_knowledge_api_smoke_flow(monkeypatch):
    tenant_id = uuid4()
    project_id = uuid4()
    source_id = uuid4()
    source = make_source(source_id, tenant_id, project_id)
    document = make_document(source_id, tenant_id, project_id)
    run = make_run(source_id, tenant_id, project_id)
    search_result = make_search_result(tenant_id, project_id, source_id)

    class FakeKnowledgeService:
        def __init__(self, db):
            self.db = db

        async def create_source(self, **kwargs):
            source.title = kwargs["title"]
            source.project_id = kwargs["project_id"]
            return source

        async def list_sources(self, **kwargs):
            return [source]

        async def get_source(self, source_id, tenant_id):
            source.id = source_id
            return source

        async def list_documents(self, **kwargs):
            return [document]

        async def start_index(self, source_id, tenant_id):
            run.source_id = source_id
            return run

        async def get_index_status(self, run_id, tenant_id):
            run.id = run_id
            run.status = "completed"
            run.progress = 100
            run.documents_processed = 1
            run.chunks_indexed = 1
            return run

        async def search(self, **kwargs):
            return [search_result]

        async def relevant_knowledge(self, **kwargs):
            return {
                "topic": kwargs["topic"],
                "project_id": kwargs.get("project_id"),
                "page_id": kwargs.get("page_id"),
                "page_context": None,
                "results": [search_result],
                "limit": kwargs["limit"],
            }

    async def no_background(run_id):
        return None

    monkeypatch.setattr(knowledge_routes, "KnowledgeService", FakeKnowledgeService)
    monkeypatch.setattr(knowledge_routes, "run_knowledge_index_background", no_background)

    app = FastAPI()
    app.include_router(knowledge_routes.router, prefix="/knowledge")
    app.dependency_overrides[knowledge_routes.get_current_user] = lambda: {
        "tenant_id": tenant_id,
        "user_id": uuid4(),
    }
    app.dependency_overrides[knowledge_routes.get_db] = lambda: object()
    client = TestClient(app)

    create_response = client.post(
        "/knowledge/sources",
        json={
            "title": "Business profile",
            "content": "We provide local SEO.",
            "project_id": str(project_id),
            "metadata": {"audience": "service businesses"},
        },
    )
    assert create_response.status_code == 201
    assert create_response.json()["title"] == "Business profile"

    sources_response = client.get("/knowledge/sources")
    assert sources_response.status_code == 200
    assert sources_response.json()["sources"][0]["id"] == str(source_id)

    source_response = client.get(f"/knowledge/sources/{source_id}")
    assert source_response.status_code == 200
    assert source_response.json()["id"] == str(source_id)

    documents_response = client.get(f"/knowledge/documents?source_id={source_id}")
    assert documents_response.status_code == 200
    assert documents_response.json()["documents"][0]["metadata"]["audience"] == "service businesses"

    index_response = client.post(f"/knowledge/sources/{source_id}/index")
    assert index_response.status_code == 202
    assert index_response.json()["qdrant_collection"] == "seo_knowledge_chunks"

    status_response = client.get(f"/knowledge/index-runs/{run.id}/status")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"

    search_response = client.get(f"/knowledge/search?project_id={project_id}&query=local%20SEO")
    assert search_response.status_code == 200
    assert search_response.json()["results"][0]["score"] == 0.93

    relevant_response = client.get(f"/knowledge/relevant?project_id={project_id}&topic=landing%20pages")
    assert relevant_response.status_code == 200
    assert relevant_response.json()["results"][0]["chunk_text"].startswith("We provide local SEO")
