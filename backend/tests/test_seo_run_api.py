from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import seo_runs as seo_run_routes


def make_run(project_id, tenant_id):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        status="queued",
        current_stage="crawl",
        stage_statuses={
            "crawl": "pending",
            "audit": "pending",
            "semantic_index": "pending",
            "content_optimization": "pending",
            "planner": "pending",
        },
        stage_errors={},
        crawl_id=None,
        audit_id=None,
        semantic_index_run_id=None,
        content_optimization_run_id=None,
        planner_run_id=None,
        error_message=None,
        started_at=None,
        completed_at=None,
        created_at=now,
        updated_at=now,
    )


def test_seo_run_api_smoke_flow(monkeypatch):
    tenant_id = uuid4()
    project_id = uuid4()
    run = make_run(project_id, tenant_id)

    class FakeSeoRunService:
        def __init__(self, db):
            self.db = db

        async def start_run(self, project_id_arg, tenant_id_arg):
            assert project_id_arg == project_id
            assert tenant_id_arg == tenant_id
            return run

        async def list_runs(self, project_id_arg, tenant_id_arg, limit=25, offset=0):
            assert project_id_arg == project_id
            assert tenant_id_arg == tenant_id
            assert limit == 10
            assert offset == 0
            return [run]

        async def get_run_status(self, run_id_arg, tenant_id_arg):
            assert run_id_arg == run.id
            assert tenant_id_arg == tenant_id
            run.status = "completed"
            run.current_stage = "completed"
            run.stage_statuses = {
                "crawl": "completed",
                "audit": "completed",
                "semantic_index": "completed",
                "content_optimization": "completed",
                "planner": "completed",
            }
            return run

    async def fake_db():
        yield object()

    async def fake_background(run_id, tenant_id_arg):
        assert run_id == run.id
        assert tenant_id_arg == tenant_id

    monkeypatch.setattr(seo_run_routes, "SeoRunService", FakeSeoRunService)
    monkeypatch.setattr(seo_run_routes, "run_seo_run_background", fake_background)

    app = FastAPI()
    app.include_router(seo_run_routes.router)
    app.dependency_overrides[seo_run_routes.get_current_user] = lambda: {
        "tenant_id": tenant_id,
        "user_id": uuid4(),
    }
    app.dependency_overrides[seo_run_routes.get_db] = fake_db
    client = TestClient(app)

    start_response = client.post(f"/projects/{project_id}/seo-run")
    assert start_response.status_code == 202
    assert start_response.json()["id"] == str(run.id)

    list_response = client.get(f"/projects/{project_id}/seo-runs?limit=10")
    assert list_response.status_code == 200
    assert list_response.json()["runs"][0]["id"] == str(run.id)

    status_response = client.get(f"/seo-runs/{run.id}/status")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"
