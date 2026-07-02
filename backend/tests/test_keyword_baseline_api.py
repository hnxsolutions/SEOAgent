from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import keyword_baselines as keyword_routes


def make_baseline(tenant_id, project_id, **overrides):
    now = datetime.utcnow()
    values = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "project_id": project_id,
        "keyword": "local seo services",
        "target_location": "Phoenix",
        "search_engine": "google",
        "device": "desktop",
        "current_position": 18,
        "current_url": "https://example.com/services",
        "search_volume": 120,
        "difficulty": 42,
        "intent": "commercial",
        "notes": "Manual check from client baseline sheet.",
        "source": "manual",
        "captured_at": now,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_keyword_baseline_api_create_list_update_delete_bulk(monkeypatch):
    tenant_id = uuid4()
    project_id = uuid4()
    baseline_id = uuid4()
    created = make_baseline(tenant_id, project_id, id=baseline_id)
    bulk_created = [
        make_baseline(tenant_id, project_id, keyword="seo audit", id=uuid4(), source="csv"),
        make_baseline(tenant_id, project_id, keyword="technical seo", id=uuid4(), source="csv", current_position=None),
    ]

    class FakeKeywordBaselineService:
        def __init__(self, db):
            self.db = db

        async def create(self, project_id, tenant_id, payload):
            assert payload.keyword == "local seo services"
            return created

        async def list(self, project_id, tenant_id, limit=100, offset=0):
            return [created]

        async def update(self, baseline_id, tenant_id, payload):
            return make_baseline(tenant_id, project_id, id=baseline_id, current_position=12)

        async def delete(self, baseline_id, tenant_id):
            return None

        async def bulk_create(self, project_id, tenant_id, payload):
            assert len(payload.items) == 2
            return bulk_created

    monkeypatch.setattr(keyword_routes, "KeywordBaselineService", FakeKeywordBaselineService)
    client = _client(tenant_id)

    create_response = client.post(
        f"/projects/{project_id}/keyword-baselines",
        json={
            "keyword": "local seo services",
            "target_location": "Phoenix",
            "device": "desktop",
            "current_position": 18,
            "current_url": "https://example.com/services",
            "intent": "commercial",
            "notes": "Manual check from client baseline sheet.",
        },
    )
    assert create_response.status_code == 201
    assert create_response.json()["keyword"] == "local seo services"

    list_response = client.get(f"/projects/{project_id}/keyword-baselines")
    assert list_response.status_code == 200
    assert list_response.json()["baselines"][0]["id"] == str(baseline_id)

    update_response = client.put(
        f"/keyword-baselines/{baseline_id}",
        json={"current_position": 12, "current_url": "https://example.com/services"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["current_position"] == 12

    bulk_response = client.post(
        f"/projects/{project_id}/keyword-baselines/bulk",
        json={
            "items": [
                {"keyword": "seo audit", "source": "csv"},
                {"keyword": "technical seo", "source": "csv", "current_position": None},
            ]
        },
    )
    assert bulk_response.status_code == 201
    assert bulk_response.json()["created_count"] == 2

    delete_response = client.delete(f"/keyword-baselines/{baseline_id}")
    assert delete_response.status_code == 204


def test_keyword_baseline_api_validates_position_and_missing_records(monkeypatch):
    tenant_id = uuid4()
    project_id = uuid4()

    class FakeKeywordBaselineService:
        def __init__(self, db):
            self.db = db

        async def create(self, project_id, tenant_id, payload):
            raise ValueError("Project not found")

        async def update(self, baseline_id, tenant_id, payload):
            raise ValueError("Keyword baseline not found")

    monkeypatch.setattr(keyword_routes, "KeywordBaselineService", FakeKeywordBaselineService)
    client = _client(tenant_id)

    invalid_response = client.post(
        f"/projects/{project_id}/keyword-baselines",
        json={"keyword": "local seo services", "current_position": 101},
    )
    assert invalid_response.status_code == 422

    missing_project_response = client.post(
        f"/projects/{project_id}/keyword-baselines",
        json={"keyword": "local seo services", "current_position": 10},
    )
    assert missing_project_response.status_code == 404

    missing_baseline_response = client.put(
        f"/keyword-baselines/{uuid4()}",
        json={"current_position": 10},
    )
    assert missing_baseline_response.status_code == 404


def _client(tenant_id):
    app = FastAPI()
    app.include_router(keyword_routes.router)
    app.dependency_overrides[keyword_routes.get_current_user] = lambda: {
        "tenant_id": tenant_id,
        "user_id": uuid4(),
    }
    app.dependency_overrides[keyword_routes.get_db] = lambda: object()
    return TestClient(app)
