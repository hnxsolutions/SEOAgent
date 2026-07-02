from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.schemas.seo_run import SeoRunReportResponse
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


def test_seo_run_report_api_returns_json_and_html(monkeypatch):
    tenant_id = uuid4()
    project_id = uuid4()
    run = make_run(project_id, tenant_id)
    run.status = "completed"
    run.current_stage = "completed"
    run.completed_at = datetime.utcnow()
    report = SeoRunReportResponse(
        run_id=run.id,
        tenant_id=tenant_id,
        project_id=project_id,
        project_name="Acme",
        website_url="https://example.com",
        run_status="completed",
        completed_at=run.completed_at,
        generated_at=datetime.utcnow(),
        crawl_pages_processed=5,
        audit_score=90,
        total_issues=2,
        issue_counts_by_severity={"high": 1, "medium": 1},
        issue_counts_by_category={"metadata": 2},
        semantic_vector_count=14,
        content_suggestions_count=1,
        planner_tasks_count=1,
        data_availability={
            "search_console": "Not connected",
            "ranking_data": "No real ranking data available",
            "serp": "No real ranking data available",
        },
        executive_summary="Acme SEO run is completed.",
        sections=[],
        top_audit_issues=[],
        semantic_summaries=[],
        content_suggestions=[],
        weekly_planner_tasks=[],
        next_actions=[],
    )

    class FakeSeoReportService:
        def __init__(self, db):
            self.db = db

        async def generate_report(self, run_id_arg, tenant_id_arg):
            assert tenant_id_arg == tenant_id
            return report if run_id_arg == run.id else None

        def render_html(self, report_arg):
            assert report_arg.run_id == report.run_id
            return "<html><body>Acme SEO Report</body></html>"

    app = FastAPI()
    app.include_router(seo_run_routes.router)
    app.dependency_overrides[seo_run_routes.get_current_user] = lambda: {
        "tenant_id": tenant_id,
        "user_id": uuid4(),
    }
    app.dependency_overrides[seo_run_routes.get_db] = lambda: object()
    monkeypatch.setattr(seo_run_routes, "SeoReportService", FakeSeoReportService)
    client = TestClient(app)

    json_response = client.get(f"/seo-runs/{run.id}/report")
    assert json_response.status_code == 200
    assert json_response.json()["project_name"] == "Acme"
    assert json_response.json()["data_availability"]["ranking_data"] == "No real ranking data available"

    html_response = client.get(f"/seo-runs/{run.id}/report.html")
    assert html_response.status_code == 200
    assert "text/html" in html_response.headers["content-type"]
    assert "Acme SEO Report" in html_response.text


def test_missing_seo_run_report_returns_404(monkeypatch):
    tenant_id = uuid4()

    class FakeSeoReportService:
        def __init__(self, db):
            self.db = db

        async def generate_report(self, run_id_arg, tenant_id_arg):
            return None

    app = FastAPI()
    app.include_router(seo_run_routes.router)
    app.dependency_overrides[seo_run_routes.get_current_user] = lambda: {
        "tenant_id": tenant_id,
        "user_id": uuid4(),
    }
    app.dependency_overrides[seo_run_routes.get_db] = lambda: object()
    monkeypatch.setattr(seo_run_routes, "SeoReportService", FakeSeoReportService)
    client = TestClient(app)

    response = client.get(f"/seo-runs/{uuid4()}/report")
    assert response.status_code == 404
