from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import schedules as schedule_routes
from app.models.scheduler import SeoScheduledRunStatus, SeoScheduleFrequency, SeoScheduleType


def test_scheduler_api_smoke_flow(monkeypatch):
    tenant_id = uuid4()
    project_id = uuid4()
    schedule_id = uuid4()
    run_id = uuid4()
    now = datetime.utcnow()

    schedule = SimpleNamespace(
        id=schedule_id,
        tenant_id=tenant_id,
        project_id=project_id,
        name="Daily GSC",
        schedule_type=SeoScheduleType.daily_gsc_sync,
        frequency=SeoScheduleFrequency.daily,
        day_of_week=None,
        day_of_month=None,
        hour=9,
        minute=0,
        timezone="UTC",
        is_enabled=True,
        last_run_at=None,
        next_run_at=now,
        created_at=now,
        updated_at=now,
    )
    run = SimpleNamespace(
        id=run_id,
        tenant_id=tenant_id,
        project_id=project_id,
        schedule_id=schedule_id,
        status=SeoScheduledRunStatus.completed,
        started_at=now,
        completed_at=now,
        error_message=None,
        planner_run_id=None,
        gsc_sync_job_id=uuid4(),
        crawl_id=None,
        audit_id=None,
        semantic_run_id=None,
        repo_scan_run_id=None,
        blog_plan_id=None,
        summary={"rows_fetched": 4},
        created_at=now,
        updated_at=now,
    )

    class FakeSchedulerService:
        def __init__(self, db):
            pass

        async def create_schedule(self, tenant_id_arg, payload):
            assert tenant_id_arg == tenant_id
            assert payload.project_id == project_id
            return schedule

        async def list_schedules(self, project_id_arg, tenant_id_arg, limit=100, offset=0):
            assert project_id_arg == project_id
            assert tenant_id_arg == tenant_id
            return [schedule]

        async def get_schedule(self, schedule_id_arg, tenant_id_arg):
            assert schedule_id_arg == schedule_id
            assert tenant_id_arg == tenant_id
            return schedule

        async def update_schedule(self, schedule_id_arg, tenant_id_arg, payload):
            assert payload.hour == 10
            schedule.hour = 10
            return schedule

        async def enable_schedule(self, schedule_id_arg, tenant_id_arg):
            schedule.is_enabled = True
            return schedule

        async def disable_schedule(self, schedule_id_arg, tenant_id_arg):
            schedule.is_enabled = False
            return schedule

        async def run_now(self, schedule_id_arg, tenant_id_arg):
            return run

        async def list_runs(self, schedule_id_arg, tenant_id_arg, limit=100, offset=0):
            return [run]

        async def get_run_status(self, run_id_arg, tenant_id_arg):
            assert run_id_arg == run_id
            return run

        async def tick(self, tenant_id=None, limit=50):
            return [run]

        async def tick_with_monitor_details(self, tenant_id=None, limit=50):
            return {
                "due_count": 1,
                "runs_created": 1,
                "runs": [run],
                "gsc_monitor_due_count": 0,
                "gsc_monitor_jobs_created": 0,
                "gsc_monitor_jobs": [],
            }

    monkeypatch.setattr(schedule_routes, "SchedulerService", FakeSchedulerService)
    monkeypatch.setattr(schedule_routes.settings, "SCHEDULER_INTERNAL_API_KEY", "internal-key")

    app = FastAPI()
    app.include_router(schedule_routes.router, prefix="/schedules")
    app.include_router(schedule_routes.internal_scheduler_router, prefix="/scheduler")
    app.include_router(schedule_routes.scheduled_runs_router, prefix="/scheduled-runs")
    app.dependency_overrides[schedule_routes.get_current_user] = lambda: {
        "tenant_id": tenant_id,
        "user_id": uuid4(),
    }
    app.dependency_overrides[schedule_routes.get_db] = lambda: object()

    client = TestClient(app)

    create_response = client.post(
        "/schedules",
        json={
            "project_id": str(project_id),
            "name": "Daily GSC",
            "schedule_type": "daily_gsc_sync",
            "frequency": "daily",
            "hour": 9,
            "minute": 0,
            "timezone": "UTC",
        },
    )
    assert create_response.status_code == 201
    assert create_response.json()["id"] == str(schedule_id)

    assert client.get(f"/schedules/projects/{project_id}").status_code == 200
    assert client.get(f"/schedules/{schedule_id}").status_code == 200
    assert client.patch(f"/schedules/{schedule_id}", json={"hour": 10}).json()["hour"] == 10
    assert client.post(f"/schedules/{schedule_id}/disable").json()["is_enabled"] is False
    assert client.post(f"/schedules/{schedule_id}/enable").json()["is_enabled"] is True

    run_now_response = client.post(f"/schedules/{schedule_id}/run-now")
    assert run_now_response.status_code == 200
    assert run_now_response.json()["summary"]["rows_fetched"] == 4

    assert client.get(f"/schedules/{schedule_id}/runs").json()["runs"][0]["id"] == str(run_id)
    assert client.get(f"/scheduled-runs/{run_id}/status").json()["id"] == str(run_id)

    tick_response = client.post("/schedules/tick", json=50)
    assert tick_response.status_code == 200
    assert tick_response.json()["runs_created"] == 1
    assert tick_response.json()["gsc_monitor_due_count"] == 0

    missing_key_response = client.post("/scheduler/tick", json=50)
    assert missing_key_response.status_code == 401

    wrong_key_response = client.post("/scheduler/tick", json=50, headers={"X-Internal-Api-Key": "wrong"})
    assert wrong_key_response.status_code == 401

    internal_tick_response = client.post("/scheduler/tick", json=50, headers={"X-Internal-Api-Key": "internal-key"})
    assert internal_tick_response.status_code == 200
    assert internal_tick_response.json()["runs_created"] == 1
