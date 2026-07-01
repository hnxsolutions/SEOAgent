from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import indexing as indexing_routes
from app.models.indexing import (
    GSCFixValidationRunStatus,
    GSCIndexingIssueSeverity,
    GSCIndexingIssueStatus,
    GSCIndexingIssueType,
    GSCUrlInspectionRunStatus,
)


def obj(**kwargs):
    return SimpleNamespace(**kwargs)


def make_run(tenant_id, project_id, property_id):
    now = datetime.utcnow()
    return obj(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        gsc_property_id=property_id,
        status=GSCUrlInspectionRunStatus.completed,
        requested_url_count=2,
        inspected_url_count=2,
        failed_url_count=0,
        started_at=now,
        completed_at=now,
        error_message=None,
        created_at=now,
    )


def make_result(tenant_id, project_id, run_id):
    now = datetime.utcnow()
    return obj(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        inspection_run_id=run_id,
        page_url="https://example.com/",
        inspection_result_link=None,
        verdict="PASS",
        coverage_state="Submitted and indexed",
        indexing_state="INDEXING_ALLOWED",
        robots_txt_state="ALLOWED",
        page_fetch_state="SUCCESSFUL",
        google_canonical="https://example.com/",
        user_canonical="https://example.com/",
        sitemap_urls=["https://example.com/sitemap.xml"],
        referring_urls=[],
        last_crawl_time=now,
        crawled_as="MOBILE",
        mobile_usability_verdict="PASS",
        rich_results_verdict="PASS",
        raw_result={"indexStatusResult": {"verdict": "PASS"}},
        created_at=now,
    )


def make_issue(tenant_id, project_id, result_id, issue_id=None, status=GSCIndexingIssueStatus.open):
    now = datetime.utcnow()
    return obj(
        id=issue_id or uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        inspection_result_id=result_id,
        page_url="https://example.com/service",
        issue_type=GSCIndexingIssueType.sitemap_missing,
        severity=GSCIndexingIssueSeverity.medium,
        likely_cause="Important page is missing from sitemap.",
        recommended_fix="Add the canonical URL to the sitemap.",
        linked_repo_issue_id=None,
        linked_patch_id=None,
        status=status,
        created_at=now,
        updated_at=now,
    )


def test_indexing_api_smoke_flow(monkeypatch):
    tenant_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    property_id = uuid4()
    issue_id = uuid4()
    run = make_run(tenant_id, project_id, property_id)
    result = make_result(tenant_id, project_id, run.id)
    issue = make_issue(tenant_id, project_id, result.id, issue_id=issue_id)
    validation_run = obj(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        issue_id=issue_id,
        patch_id=None,
        pull_request_id=None,
        status=GSCFixValidationRunStatus.completed,
        validation_after_days=7,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
    )
    validation_result = obj(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        validation_run_id=validation_run.id,
        issue_id=issue_id,
        page_url=issue.page_url,
        previous_issue_type=GSCIndexingIssueType.sitemap_missing,
        current_verdict="PASS",
        current_coverage_state="Submitted and indexed",
        fixed=True,
        still_failing=False,
        notes="Fixed.",
        raw_result={"indexStatusResult": {"verdict": "PASS"}},
        created_at=datetime.utcnow(),
    )

    class FakeIndexingService:
        def __init__(self, db):
            self.db = db

        async def inspect_project(self, **kwargs):
            assert kwargs["project_id"] == project_id
            return run

        async def list_runs(self, project_id_arg, tenant_id_arg, limit=100, offset=0):
            return [run]

        async def get_run_details(self, run_id, tenant_id_arg):
            return {"run": run, "results": [result], "issues": [issue]}

        async def list_issues(self, project_id_arg, tenant_id_arg, **kwargs):
            return [issue]

        async def get_issue(self, issue_id_arg, tenant_id_arg):
            return issue

        async def create_fix_plan(self, issue_id_arg, tenant_id_arg):
            issue.status = GSCIndexingIssueStatus.fix_proposed
            return {"issue": issue, "planner_task": None, "repo_issue": None, "patch": None, "safety": "Review-only"}

        async def ignore_issue(self, issue_id_arg, tenant_id_arg):
            return make_issue(tenant_id, project_id, result.id, issue_id=issue_id_arg, status=GSCIndexingIssueStatus.ignored)

        async def validate_issue(self, issue_id_arg, tenant_id_arg, validation_after_days=7, run_now=True):
            return {"validation_run": validation_run, "result": validation_result, "issue": issue}

        async def summary(self, project_id_arg, tenant_id_arg):
            return {
                "project_id": project_id_arg,
                "url_inspection_connected": True,
                "indexed_urls": 1,
                "not_indexed_urls": 1,
                "issues_count": 1,
                "issues_by_type": {"sitemap_missing": 1},
                "issues_by_status": {"open": 1},
                "latest_run": run,
                "top_issues": [issue],
                "next_validation_date": datetime.utcnow() + timedelta(days=7),
            }

    monkeypatch.setattr(indexing_routes, "IndexingService", FakeIndexingService)

    app = FastAPI()
    app.include_router(indexing_routes.router, prefix="/indexing")
    app.dependency_overrides[indexing_routes.get_current_user] = lambda: {"tenant_id": tenant_id, "user_id": user_id}
    app.dependency_overrides[indexing_routes.get_db] = lambda: object()
    client = TestClient(app)

    inspect_response = client.post(f"/indexing/projects/{project_id}/inspect", json={"urls": ["https://example.com/"]})
    assert inspect_response.status_code == 200
    assert inspect_response.json()["inspected_url_count"] == 2

    runs_response = client.get(f"/indexing/projects/{project_id}/runs")
    assert runs_response.status_code == 200
    assert runs_response.json()["runs"][0]["status"] == "completed"

    run_response = client.get(f"/indexing/runs/{run.id}")
    assert run_response.status_code == 200
    assert run_response.json()["results"][0]["verdict"] == "PASS"

    issues_response = client.get(f"/indexing/projects/{project_id}/issues")
    assert issues_response.status_code == 200
    assert issues_response.json()["issues"][0]["issue_type"] == "sitemap_missing"

    issue_response = client.get(f"/indexing/issues/{issue_id}")
    assert issue_response.status_code == 200
    assert issue_response.json()["id"] == str(issue_id)

    fix_response = client.post(f"/indexing/issues/{issue_id}/create-fix-plan")
    assert fix_response.status_code == 200
    assert fix_response.json()["issue"]["status"] == "fix_proposed"

    ignore_response = client.post(f"/indexing/issues/{issue_id}/ignore")
    assert ignore_response.status_code == 200
    assert ignore_response.json()["status"] == "ignored"

    validate_response = client.post(f"/indexing/issues/{issue_id}/validate", json={"validation_after_days": 7, "run_now": True})
    assert validate_response.status_code == 200
    assert validate_response.json()["result"]["fixed"] is True

    summary_response = client.get(f"/indexing/projects/{project_id}/summary")
    assert summary_response.status_code == 200
    assert summary_response.json()["url_inspection_connected"] is True
