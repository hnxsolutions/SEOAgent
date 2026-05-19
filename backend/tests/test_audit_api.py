from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import audit as audit_routes


def test_audit_api_smoke_flow(monkeypatch):
    tenant_id = uuid4()
    audit_id = uuid4()
    crawl_id = uuid4()
    page_id = uuid4()
    issue_id = uuid4()
    now = datetime.utcnow()

    class FakeAuditService:
        def __init__(self, db):
            self.db = db

        async def start_audit(self, crawl_job_id, tenant_id):
            return SimpleNamespace(
                id=audit_id,
                crawl_job_id=crawl_job_id,
                project_id=None,
                tenant_id=tenant_id,
                status="pending",
                progress=0,
                site_score=None,
                total_pages=0,
                total_issues=0,
                issue_counts_by_severity={},
                issue_counts_by_category={},
                error_message=None,
                started_at=None,
                completed_at=None,
                created_at=now,
                updated_at=now,
            )

        async def get_audit_status(self, audit_run_id, tenant_id):
            return SimpleNamespace(
                id=audit_run_id,
                crawl_job_id=crawl_id,
                project_id=None,
                tenant_id=tenant_id,
                status="completed",
                progress=100,
                site_score=72,
                total_pages=4,
                total_issues=12,
                issue_counts_by_severity={"high": 2},
                issue_counts_by_category={"metadata": 5},
                error_message=None,
                started_at=now,
                completed_at=now,
                created_at=now,
                updated_at=now,
            )

        async def list_issues(self, **kwargs):
            return [
                SimpleNamespace(
                    id=issue_id,
                    audit_run_id=audit_id,
                    crawl_job_id=crawl_id,
                    crawl_page_id=page_id,
                    project_id=None,
                    tenant_id=tenant_id,
                    issue_type="missing_title",
                    title="Missing title",
                    message="Page is missing a title tag.",
                    recommendation="Add a unique title.",
                    severity="high",
                    category="metadata",
                    status="open",
                    url="https://example.com",
                    evidence={},
                    score_impact=15,
                    created_at=now,
                    updated_at=now,
                )
            ]

        async def get_page_score(self, page_id, tenant_id, audit_run_id=None):
            return SimpleNamespace(
                id=uuid4(),
                audit_run_id=audit_id,
                crawl_job_id=crawl_id,
                crawl_page_id=page_id,
                project_id=None,
                tenant_id=tenant_id,
                url="https://example.com",
                score=85,
                issue_count=1,
                critical_issues=0,
                high_issues=1,
                medium_issues=0,
                low_issues=0,
                score_breakdown={"base_score": 100, "score_loss": 15},
                created_at=now,
                updated_at=now,
            )

        async def get_site_summary(self, crawl_job_id, tenant_id, audit_run_id=None):
            return {
                "audit_run_id": audit_id,
                "crawl_job_id": crawl_job_id,
                "project_id": None,
                "status": "completed",
                "site_score": 72,
                "total_pages": 4,
                "total_issues": 12,
                "issue_counts_by_severity": {"high": 2},
                "issue_counts_by_category": {"metadata": 5},
                "top_issue_types": {"missing_title": 1},
                "started_at": now,
                "completed_at": now,
            }

    async def no_background(audit_run_id):
        return None

    monkeypatch.setattr(audit_routes, "AuditService", FakeAuditService)
    monkeypatch.setattr(audit_routes, "run_audit_background", no_background)

    app = FastAPI()
    app.include_router(audit_routes.router, prefix="/audits")
    app.dependency_overrides[audit_routes.get_current_user] = lambda: {
        "tenant_id": tenant_id,
        "user_id": uuid4(),
    }
    app.dependency_overrides[audit_routes.get_db] = lambda: object()

    client = TestClient(app)

    start_response = client.post(f"/audits/crawls/{crawl_id}/start")
    assert start_response.status_code == 202
    assert start_response.json()["status"] == "pending"

    status_response = client.get(f"/audits/{audit_id}/status")
    assert status_response.status_code == 200
    assert status_response.json()["site_score"] == 72

    issues_response = client.get(f"/audits/issues?crawl_id={crawl_id}")
    assert issues_response.status_code == 200
    assert issues_response.json()["issues"][0]["issue_type"] == "missing_title"

    score_response = client.get(f"/audits/pages/{page_id}/score?audit_id={audit_id}")
    assert score_response.status_code == 200
    assert score_response.json()["score"] == 85

    summary_response = client.get(f"/audits/crawls/{crawl_id}/summary?audit_id={audit_id}")
    assert summary_response.status_code == 200
    assert summary_response.json()["top_issue_types"] == {"missing_title": 1}
