"""API tests for project creation, including autonomous SEO-run kickoff."""
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import projects as projects_routes


def _make_project(tenant_id):
    now = "2026-07-15T00:00:00"
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_id=uuid4(),
        is_active=True,
        name="Acme SEO",
        domain="example.com",
        description=None,
        keywords=None,
        business_name=None,
        industry=None,
        target_location=None,
        target_audience=None,
        primary_services=None,
        target_keywords=None,
        competitor_urls=None,
        seo_goal=None,
        brand_tone=None,
        status="active",
        created_at=now,
        updated_at=None,
    )


def _build_client(monkeypatch, tenant_id, *, auto_run, start_run_raises=False, scheduled=None):
    project = _make_project(tenant_id)
    run = SimpleNamespace(id=uuid4())

    class FakeProjectService:
        def __init__(self, db):
            self.db = db

        async def create_project(self, project_data, tenant_id, user_id):
            return project

    class FakeSeoRunService:
        def __init__(self, db):
            self.db = db

        async def start_run(self, project_id_arg, tenant_id_arg):
            assert project_id_arg == project.id
            assert tenant_id_arg == tenant_id
            if start_run_raises:
                raise RuntimeError("boom")
            return run

    async def fake_background(run_id, tenant_id_arg):
        if scheduled is not None:
            scheduled.append((run_id, tenant_id_arg))

    async def fake_db():
        yield object()

    monkeypatch.setattr(projects_routes, "ProjectService", FakeProjectService)
    monkeypatch.setattr(projects_routes, "SeoRunService", FakeSeoRunService)
    monkeypatch.setattr(projects_routes, "run_seo_run_background", fake_background)
    monkeypatch.setattr(projects_routes.settings, "AUTO_RUN_SEO_ON_PROJECT_CREATE", auto_run)
    # Force the BackgroundTasks fallback path so the dispatch is deterministic in
    # tests (no dependency on a live Redis/RQ queue).
    monkeypatch.setattr(projects_routes.settings, "QUEUE_ENABLED", False)

    app = FastAPI()
    app.include_router(projects_routes.router)
    app.dependency_overrides[projects_routes.get_current_user] = lambda: {
        "tenant_id": tenant_id,
        "user_id": uuid4(),
    }
    app.dependency_overrides[projects_routes.get_db] = fake_db
    return TestClient(app), project, run


def test_create_project_auto_starts_seo_run_when_enabled(monkeypatch):
    tenant_id = uuid4()
    scheduled = []
    client, project, run = _build_client(monkeypatch, tenant_id, auto_run=True, scheduled=scheduled)

    response = client.post("/", json={"name": "Acme SEO", "domain": "example.com"})

    assert response.status_code == 201
    assert response.json()["id"] == str(project.id)
    # Background task actually ran with the started run's id.
    assert scheduled == [(run.id, tenant_id)]


def test_create_project_does_not_start_run_when_disabled(monkeypatch):
    tenant_id = uuid4()
    scheduled = []
    client, project, _ = _build_client(monkeypatch, tenant_id, auto_run=False, scheduled=scheduled)

    response = client.post("/", json={"name": "Acme SEO", "domain": "example.com"})

    assert response.status_code == 201
    assert scheduled == []


def test_create_project_succeeds_even_if_auto_run_fails(monkeypatch):
    tenant_id = uuid4()
    scheduled = []
    client, project, _ = _build_client(
        monkeypatch, tenant_id, auto_run=True, start_run_raises=True, scheduled=scheduled
    )

    response = client.post("/", json={"name": "Acme SEO", "domain": "example.com"})

    # Project creation must still succeed; no run scheduled.
    assert response.status_code == 201
    assert response.json()["id"] == str(project.id)
    assert scheduled == []
