from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import planner as planner_routes
from app.models.planner import (
    SeoPlannerRunStatus,
    SeoPlannerRunType,
    SeoTaskEffort,
    SeoTaskImpact,
    SeoTaskPriority,
    SeoTaskSourceType,
    SeoTaskStatus,
    SeoTaskType,
)


def test_planner_api_smoke_flow(monkeypatch):
    tenant_id = uuid4()
    project_id = uuid4()
    run_id = uuid4()
    task_id = uuid4()
    report_id = uuid4()
    now = datetime.utcnow()

    run = SimpleNamespace(
        id=run_id,
        tenant_id=tenant_id,
        project_id=project_id,
        status=SeoPlannerRunStatus.completed,
        run_type=SeoPlannerRunType.manual,
        target_week_start=now,
        target_week_end=now,
        crawl_id=None,
        audit_id=None,
        semantic_run_id=None,
        internal_link_run_id=None,
        content_optimization_run_id=None,
        geo_aeo_run_id=None,
        gsc_sync_job_id=None,
        blog_plan_id=None,
        repo_scan_run_id=None,
        tasks_created=1,
        high_priority_tasks=1,
        error_message=None,
        started_at=now,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )
    task = SimpleNamespace(
        id=task_id,
        tenant_id=tenant_id,
        project_id=project_id,
        planner_run_id=run_id,
        task_type=SeoTaskType.metadata_rewrite,
        title="Rewrite metadata",
        description="Improve title and description.",
        source_type=SeoTaskSourceType.search_console,
        source_reference_id=uuid4(),
        target_page_url="https://example.com",
        target_keyword="seo services",
        priority=SeoTaskPriority.high,
        priority_score=88,
        estimated_impact=SeoTaskImpact.high,
        effort=SeoTaskEffort.low,
        status=SeoTaskStatus.todo,
        due_date=now,
        created_at=now,
        updated_at=now,
    )
    report = SimpleNamespace(
        id=report_id,
        tenant_id=tenant_id,
        project_id=project_id,
        planner_run_id=run_id,
        summary="Weekly SEO plan created 1 new task.",
        wins=[],
        risks=[],
        technical_seo_summary={},
        search_console_summary={},
        content_summary={},
        geo_aeo_summary={},
        blog_summary={},
        repo_patch_summary={},
        next_week_priorities=[],
        created_at=now,
    )

    class FakePlannerService:
        def __init__(self, db):
            self.db = db

        async def run_project(self, project_id, tenant_id, run_type=SeoPlannerRunType.manual, target_week_start=None):
            return run

        async def get_run_status(self, run_id, tenant_id):
            return run

        async def list_runs(self, project_id, tenant_id, limit=100, offset=0):
            return [run]

        async def list_tasks(self, project_id, tenant_id, status=None, limit=100, offset=0):
            return [task]

        async def get_task(self, task_id, tenant_id):
            return task

        async def update_task_status(self, task_id, tenant_id, status):
            task.status = status
            return task

        async def get_report(self, run_id, tenant_id):
            return report

        async def project_summary(self, project_id, tenant_id):
            return {
                "project_id": project_id,
                "open_tasks": 1,
                "total_tasks": 1,
                "tasks_by_status": {"todo": 1},
                "tasks_by_priority": {"high": 1},
                "latest_run_id": run_id,
                "latest_run_status": SeoPlannerRunStatus.completed,
                "top_tasks": [task],
            }

        async def list_duplicate_tasks(self, project_id, tenant_id):
            return {
                "project_id": project_id,
                "dry_run": True,
                "duplicate_groups": [],
                "duplicate_group_count": 0,
                "duplicate_task_count": 0,
                "skipped_task_count": 0,
            }

        async def dedupe_preview(self, project_id, tenant_id):
            return await self.list_duplicate_tasks(project_id, tenant_id)

        async def dedupe_apply(self, project_id, tenant_id):
            return {
                "project_id": project_id,
                "dry_run": False,
                "duplicate_groups": [],
                "duplicate_group_count": 0,
                "duplicate_task_count": 0,
                "skipped_task_count": 0,
            }

    monkeypatch.setattr(planner_routes, "PlannerService", FakePlannerService)

    app = FastAPI()
    app.include_router(planner_routes.router, prefix="/planner")
    app.dependency_overrides[planner_routes.get_current_user] = lambda: {
        "tenant_id": tenant_id,
        "user_id": uuid4(),
    }
    app.dependency_overrides[planner_routes.get_db] = lambda: object()
    client = TestClient(app)

    run_response = client.post(f"/planner/projects/{project_id}/run", json={"run_type": "manual"})
    assert run_response.status_code == 200
    assert run_response.json()["tasks_created"] == 1

    status_response = client.get(f"/planner/runs/{run_id}/status")
    assert status_response.status_code == 200

    runs_response = client.get(f"/planner/projects/{project_id}/runs")
    assert runs_response.status_code == 200
    assert runs_response.json()["runs"][0]["id"] == str(run_id)

    tasks_response = client.get(f"/planner/projects/{project_id}/tasks")
    assert tasks_response.status_code == 200
    assert tasks_response.json()["tasks"][0]["task_type"] == "metadata_rewrite"

    task_response = client.get(f"/planner/tasks/{task_id}")
    assert task_response.status_code == 200

    approve_response = client.post(f"/planner/tasks/{task_id}/approve")
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"

    in_progress_response = client.post(f"/planner/tasks/{task_id}/mark-in-progress")
    assert in_progress_response.status_code == 200
    assert in_progress_response.json()["status"] == "in_progress"

    completed_response = client.post(f"/planner/tasks/{task_id}/mark-completed")
    assert completed_response.status_code == 200
    assert completed_response.json()["status"] == "completed"

    reject_response = client.post(f"/planner/tasks/{task_id}/reject")
    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"

    report_response = client.get(f"/planner/runs/{run_id}/report")
    assert report_response.status_code == 200
    assert report_response.json()["summary"].startswith("Weekly SEO plan")

    summary_response = client.get(f"/planner/projects/{project_id}/summary")
    assert summary_response.status_code == 200
    assert summary_response.json()["open_tasks"] == 1

    duplicates_response = client.get(f"/planner/projects/{project_id}/duplicates")
    assert duplicates_response.status_code == 200
    assert duplicates_response.json()["duplicate_group_count"] == 0

    preview_response = client.post(f"/planner/projects/{project_id}/dedupe-preview")
    assert preview_response.status_code == 200
    assert preview_response.json()["dry_run"] is True

    apply_response = client.post(f"/planner/projects/{project_id}/dedupe-apply")
    assert apply_response.status_code == 200
    assert apply_response.json()["dry_run"] is False
