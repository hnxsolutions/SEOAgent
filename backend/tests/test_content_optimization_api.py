from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import content_optimization as content_routes


def make_run(crawl_id, tenant_id):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=uuid4(),
        crawl_id=crawl_id,
        project_id=None,
        tenant_id=tenant_id,
        status="pending",
        progress=0,
        model="qwen2.5:3b",
        total_pages=0,
        total_suggestions=0,
        error_message=None,
        started_at=None,
        completed_at=None,
        created_at=now,
        updated_at=now,
    )


def make_suggestion(crawl_id, page_id, tenant_id, suggestion_id=None, status="suggested"):
    now = datetime.utcnow()
    return SimpleNamespace(
        id=suggestion_id or uuid4(),
        run_id=uuid4(),
        tenant_id=tenant_id,
        project_id=None,
        crawl_id=crawl_id,
        page_id=page_id,
        suggestion_type="seo_title",
        current_value="Old title",
        suggested_value="A Better Search Title for This Page",
        reason="Improve metadata.",
        priority_score=82,
        confidence_score=88,
        status=status,
        created_at=now,
        updated_at=now,
        approved_at=None,
        rejected_at=None,
        applied_at=None,
    )


def test_content_optimization_api_smoke_flow(monkeypatch):
    tenant_id = uuid4()
    crawl_id = uuid4()
    page_id = uuid4()
    suggestion_id = uuid4()
    run = make_run(crawl_id, tenant_id)
    suggestion = make_suggestion(crawl_id, page_id, tenant_id, suggestion_id)

    class FakeContentOptimizationService:
        def __init__(self, db):
            self.db = db

        async def start_generation(self, crawl_id, tenant_id):
            return run

        async def get_run_status(self, run_id, tenant_id):
            run.id = run_id
            run.status = "completed"
            run.progress = 100
            run.total_pages = 1
            run.total_suggestions = 1
            return run

        async def list_suggestions(self, **kwargs):
            return [suggestion]

        async def update_status(self, suggestion_id, tenant_id, status):
            return make_suggestion(
                crawl_id,
                page_id,
                tenant_id,
                suggestion_id=suggestion_id,
                status=status.value if hasattr(status, "value") else status,
            )

        async def summary(self, crawl_id, tenant_id):
            return {
                "crawl_id": crawl_id,
                "project_id": None,
                "total_suggestions": 1,
                "pages_with_suggestions": 1,
                "average_priority_score": 82,
                "average_confidence_score": 88,
                "suggestions_by_status": {"suggested": 1},
                "suggestions_by_type": {"seo_title": 1},
            }

    async def no_background(run_id):
        return None

    monkeypatch.setattr(content_routes, "ContentOptimizationService", FakeContentOptimizationService)
    monkeypatch.setattr(content_routes, "run_content_optimization_background", no_background)

    app = FastAPI()
    app.include_router(content_routes.router, prefix="/content-optimization")
    app.dependency_overrides[content_routes.get_current_user] = lambda: {
        "tenant_id": tenant_id,
        "user_id": uuid4(),
    }
    app.dependency_overrides[content_routes.get_db] = lambda: object()
    client = TestClient(app)

    generate_response = client.post(f"/content-optimization/crawls/{crawl_id}/generate")
    assert generate_response.status_code == 202
    assert generate_response.json()["model"] == "qwen2.5:3b"

    status_response = client.get(f"/content-optimization/runs/{run.id}/status")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"

    crawl_suggestions = client.get(f"/content-optimization/crawls/{crawl_id}/suggestions")
    assert crawl_suggestions.status_code == 200
    assert crawl_suggestions.json()["suggestions"][0]["suggestion_type"] == "seo_title"

    page_suggestions = client.get(f"/content-optimization/pages/{page_id}/suggestions")
    assert page_suggestions.status_code == 200
    assert page_suggestions.json()["suggestions"][0]["page_id"] == str(page_id)

    approve_response = client.post(f"/content-optimization/suggestions/{suggestion_id}/approve")
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"

    reject_response = client.post(f"/content-optimization/suggestions/{suggestion_id}/reject")
    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"

    applied_response = client.post(f"/content-optimization/suggestions/{suggestion_id}/mark-applied")
    assert applied_response.status_code == 200
    assert applied_response.json()["status"] == "applied"

    summary_response = client.get(f"/content-optimization/crawls/{crawl_id}/summary")
    assert summary_response.status_code == 200
    assert summary_response.json()["suggestions_by_type"] == {"seo_title": 1}
