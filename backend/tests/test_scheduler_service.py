from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.planner import SeoPlannerRunStatus
from app.models.scheduler import (
    SeoScheduledRunStatus,
    SeoSchedule,
    SeoScheduleFrequency,
    SeoScheduleType,
)
from app.services.scheduler import SchedulerService
from app.services.search_console import SearchConsoleConfigurationError
from app.schemas.scheduler import SeoScheduleCreate, SeoScheduleUpdate


class FakeDB:
    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None


def make_schedule(
    *,
    tenant_id=None,
    project_id=None,
    schedule_type=SeoScheduleType.weekly_full_seo,
    frequency=SeoScheduleFrequency.weekly,
    next_run_at=None,
    is_enabled=True,
):
    schedule = SeoSchedule(
        tenant_id=tenant_id or uuid4(),
        project_id=project_id or uuid4(),
        name="Scheduled SEO",
        schedule_type=schedule_type,
        frequency=frequency,
        day_of_week=0,
        day_of_month=1,
        hour=9,
        minute=0,
        timezone="UTC",
        is_enabled=is_enabled,
        next_run_at=next_run_at,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    schedule.id = uuid4()
    return schedule


class FakeSchedulerRepository:
    def __init__(self, tenant_id=None, project_id=None):
        self.tenant_id = tenant_id or uuid4()
        self.project_id = project_id or uuid4()
        self.project = SimpleNamespace(id=self.project_id, tenant_id=self.tenant_id, name="Acme", domain="https://example.com")
        self.schedules = []
        self.runs = []
        self.running = False
        self.connection = None
        self.blog_plan = None

    async def get_project(self, project_id, tenant_id):
        return self.project if project_id == self.project_id and tenant_id == self.tenant_id else None

    async def create_schedule(self, values):
        schedule = SeoSchedule(**values)
        schedule.id = uuid4()
        schedule.created_at = datetime.utcnow()
        schedule.updated_at = datetime.utcnow()
        self.schedules.append(schedule)
        return schedule

    async def get_schedule(self, schedule_id, tenant_id=None):
        return next((item for item in self.schedules if item.id == schedule_id and (tenant_id is None or item.tenant_id == tenant_id)), None)

    async def list_schedules(self, project_id, tenant_id, limit=100, offset=0):
        return [item for item in self.schedules if item.project_id == project_id and item.tenant_id == tenant_id][offset:offset + limit]

    async def update_schedule(self, schedule, values):
        for key, value in values.items():
            setattr(schedule, key, value)
        schedule.updated_at = datetime.utcnow()
        return schedule

    async def due_schedules(self, now, tenant_id=None, limit=50):
        due = [
            item for item in self.schedules
            if item.is_enabled and item.next_run_at and item.next_run_at <= now and (tenant_id is None or item.tenant_id == tenant_id)
        ]
        return due[:limit]

    async def has_running_run(self, schedule_id):
        return self.running

    async def create_run(self, schedule, status=SeoScheduledRunStatus.queued):
        run = SimpleNamespace(
            id=uuid4(),
            tenant_id=schedule.tenant_id,
            project_id=schedule.project_id,
            schedule_id=schedule.id,
            status=status,
            started_at=None,
            completed_at=None,
            error_message=None,
            planner_run_id=None,
            gsc_sync_job_id=None,
            crawl_id=None,
            audit_id=None,
            semantic_run_id=None,
            repo_scan_run_id=None,
            blog_plan_id=None,
            summary=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.runs.append(run)
        return run

    async def get_run(self, run_id, tenant_id=None):
        return next((item for item in self.runs if item.id == run_id and (tenant_id is None or item.tenant_id == tenant_id)), None)

    async def list_runs(self, schedule_id, tenant_id, limit=100, offset=0):
        return [item for item in self.runs if item.schedule_id == schedule_id and item.tenant_id == tenant_id][offset:offset + limit]

    async def set_run_status(self, run, status, error_message=None):
        run.status = status
        run.error_message = error_message
        run.updated_at = datetime.utcnow()
        if status == SeoScheduledRunStatus.running:
            run.started_at = run.started_at or run.updated_at
        return run

    async def finish_run(self, run, *, status, ids=None, summary=None, error_message=None):
        ids = ids or {}
        run.status = status
        run.planner_run_id = ids.get("planner_run_id")
        run.gsc_sync_job_id = ids.get("gsc_sync_job_id")
        run.crawl_id = ids.get("crawl_id")
        run.audit_id = ids.get("audit_id")
        run.semantic_run_id = ids.get("semantic_run_id")
        run.repo_scan_run_id = ids.get("repo_scan_run_id")
        run.blog_plan_id = ids.get("blog_plan_id")
        run.summary = summary or {}
        run.error_message = error_message
        run.completed_at = datetime.utcnow()
        run.updated_at = run.completed_at
        return run

    async def mark_schedule_executed(self, schedule, *, last_run_at, next_run_at):
        schedule.last_run_at = last_run_at
        schedule.next_run_at = next_run_at
        return schedule

    async def latest_blog_plan(self, project_id, tenant_id):
        return self.blog_plan

    async def first_repo_connection(self, project_id, tenant_id):
        return self.connection


def make_service(repository):
    service = SchedulerService(FakeDB())
    service.repository = repository
    return service


@pytest.mark.asyncio
async def test_schedule_creation_and_next_run_calculation():
    repo = FakeSchedulerRepository()
    service = make_service(repo)
    payload = SeoScheduleCreate(
        project_id=repo.project_id,
        name="Daily GSC",
        schedule_type=SeoScheduleType.daily_gsc_sync,
        frequency=SeoScheduleFrequency.daily,
        hour=9,
        minute=30,
        timezone="Asia/Calcutta",
    )

    schedule = await service.create_schedule(repo.tenant_id, payload)

    assert schedule.next_run_at is not None
    calculated = service.calculate_next_run(
        {
            "frequency": SeoScheduleFrequency.weekly,
            "day_of_week": 2,
            "hour": 10,
            "minute": 15,
            "timezone": "UTC",
        },
        after=datetime(2026, 5, 20, 8, 0),
    )
    assert calculated == datetime(2026, 5, 20, 10, 15)


@pytest.mark.asyncio
async def test_enable_disable_schedule():
    repo = FakeSchedulerRepository()
    schedule = make_schedule(tenant_id=repo.tenant_id, project_id=repo.project_id)
    repo.schedules.append(schedule)
    service = make_service(repo)

    disabled = await service.disable_schedule(schedule.id, repo.tenant_id)
    assert disabled.is_enabled is False
    assert disabled.next_run_at is None

    enabled = await service.enable_schedule(schedule.id, repo.tenant_id)
    assert enabled.is_enabled is True
    assert enabled.next_run_at is not None


@pytest.mark.asyncio
async def test_manual_run_now_creates_completed_planner_run(monkeypatch):
    repo = FakeSchedulerRepository()
    schedule = make_schedule(tenant_id=repo.tenant_id, project_id=repo.project_id)
    repo.schedules.append(schedule)
    service = make_service(repo)
    planner_id = uuid4()

    class FakePlannerService:
        def __init__(self, db):
            pass

        async def run_project(self, project_id, tenant_id, run_type, target_week_start=None):
            return SimpleNamespace(
                id=planner_id,
                status=SeoPlannerRunStatus.completed,
                crawl_id=None,
                audit_id=None,
                semantic_run_id=None,
                gsc_sync_job_id=None,
                repo_scan_run_id=None,
                blog_plan_id=None,
                tasks_created=4,
                high_priority_tasks=2,
            )

    monkeypatch.setattr(service, "planner_service_class", FakePlannerService)

    run = await service.run_now(schedule.id, repo.tenant_id)

    assert run.status == SeoScheduledRunStatus.completed
    assert run.planner_run_id == planner_id
    assert run.summary["tasks_created"] == 4


@pytest.mark.asyncio
async def test_tick_finds_due_and_skips_disabled(monkeypatch):
    repo = FakeSchedulerRepository()
    due = make_schedule(
        tenant_id=repo.tenant_id,
        project_id=repo.project_id,
        next_run_at=datetime.utcnow() - timedelta(minutes=1),
    )
    disabled = make_schedule(
        tenant_id=repo.tenant_id,
        project_id=repo.project_id,
        next_run_at=datetime.utcnow() - timedelta(minutes=1),
        is_enabled=False,
    )
    repo.schedules.extend([due, disabled])
    service = make_service(repo)

    class FakePlannerService:
        def __init__(self, db):
            pass

        async def run_project(self, project_id, tenant_id, run_type, target_week_start=None):
            return SimpleNamespace(
                id=uuid4(),
                status=SeoPlannerRunStatus.completed,
                crawl_id=None,
                audit_id=None,
                semantic_run_id=None,
                gsc_sync_job_id=None,
                repo_scan_run_id=None,
                blog_plan_id=None,
                tasks_created=1,
                high_priority_tasks=0,
            )

    monkeypatch.setattr(service, "planner_service_class", FakePlannerService)

    runs = await service.tick(tenant_id=repo.tenant_id)

    assert len(runs) == 1
    assert runs[0].schedule_id == due.id
    assert due.last_run_at is not None
    assert disabled.last_run_at is None


@pytest.mark.asyncio
async def test_duplicate_running_schedule_is_skipped():
    repo = FakeSchedulerRepository()
    repo.running = True
    schedule = make_schedule(tenant_id=repo.tenant_id, project_id=repo.project_id)
    service = make_service(repo)

    run = await service.execute_schedule(schedule)

    assert run.status == SeoScheduledRunStatus.skipped
    assert "already" in run.error_message


@pytest.mark.asyncio
async def test_daily_gsc_sync_skip_when_oauth_missing(monkeypatch):
    repo = FakeSchedulerRepository()
    schedule = make_schedule(
        tenant_id=repo.tenant_id,
        project_id=repo.project_id,
        schedule_type=SeoScheduleType.daily_gsc_sync,
        frequency=SeoScheduleFrequency.daily,
    )
    service = make_service(repo)

    class FakeGSCService:
        def __init__(self, db):
            pass

        async def sync_project(self, **kwargs):
            raise SearchConsoleConfigurationError("OAuth credentials are not configured")

    monkeypatch.setattr(service, "search_console_service_class", FakeGSCService)

    run = await service.execute_schedule(schedule)

    assert run.status == SeoScheduledRunStatus.skipped
    assert "OAuth" in run.error_message


@pytest.mark.asyncio
async def test_weekly_full_seo_creates_planner_run(monkeypatch):
    repo = FakeSchedulerRepository()
    service = make_service(repo)
    schedule = make_schedule(tenant_id=repo.tenant_id, project_id=repo.project_id)

    class FakePlannerService:
        def __init__(self, db):
            pass

        async def run_project(self, project_id, tenant_id, run_type, target_week_start=None):
            return SimpleNamespace(
                id=uuid4(),
                status=SeoPlannerRunStatus.completed,
                crawl_id=uuid4(),
                audit_id=uuid4(),
                semantic_run_id=uuid4(),
                gsc_sync_job_id=None,
                repo_scan_run_id=None,
                blog_plan_id=None,
                tasks_created=3,
                high_priority_tasks=1,
            )

    monkeypatch.setattr(service, "planner_service_class", FakePlannerService)

    run = await service.execute_schedule(schedule)

    assert run.status == SeoScheduledRunStatus.completed
    assert run.planner_run_id is not None
    assert run.crawl_id is not None
    assert run.audit_id is not None
    assert run.semantic_run_id is not None


@pytest.mark.asyncio
async def test_weekly_repo_scan_uses_repo_scan_service(monkeypatch):
    repo = FakeSchedulerRepository()
    repo.connection = SimpleNamespace(id=uuid4())
    schedule = make_schedule(
        tenant_id=repo.tenant_id,
        project_id=repo.project_id,
        schedule_type=SeoScheduleType.weekly_repo_scan,
        frequency=SeoScheduleFrequency.weekly,
    )
    service = make_service(repo)
    scan_id = uuid4()

    class FakeRepoAgentService:
        def __init__(self, db):
            pass

        async def scan_connection(self, connection_id, tenant_id):
            return SimpleNamespace(id=scan_id, files_scanned=5, issues_found=2)

        async def generate_patches(self, scan_id_arg, tenant_id):
            assert scan_id_arg == scan_id
            return [SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())]

    monkeypatch.setattr(service, "repo_agent_service_class", FakeRepoAgentService)

    run = await service.execute_schedule(schedule)

    assert run.status == SeoScheduledRunStatus.completed
    assert run.repo_scan_run_id == scan_id
    assert run.summary["patches_proposed"] == 2


@pytest.mark.asyncio
async def test_weekly_indexing_monitor_manual_run(monkeypatch):
    repo = FakeSchedulerRepository()
    schedule = make_schedule(
        tenant_id=repo.tenant_id,
        project_id=repo.project_id,
        schedule_type=SeoScheduleType.weekly_indexing_monitor,
        frequency=SeoScheduleFrequency.weekly,
    )
    service = make_service(repo)
    inspection_run_id = uuid4()

    class FakeIndexingService:
        def __init__(self, db):
            pass

        async def run_weekly_monitor(self, project_id, tenant_id):
            assert project_id == repo.project_id
            assert tenant_id == repo.tenant_id
            return {
                "gsc_sync": {"status": "completed", "rows_fetched": 10},
                "inspection_run_id": inspection_run_id,
                "inspection_status": "completed",
                "inspected_url_count": 4,
                "failed_url_count": 0,
                "issues_count": 1,
                "issues_by_type": {"sitemap_missing": 1},
                "weekly_indexing_report": {
                    "indexed_urls": 3,
                    "not_indexed_urls": 1,
                    "top_issues": [],
                },
            }

    monkeypatch.setattr(service, "indexing_service_class", FakeIndexingService)

    run = await service.execute_schedule(schedule, manual_trigger=True)

    assert run.status == SeoScheduledRunStatus.completed
    assert run.summary["schedule_type"] == SeoScheduleType.weekly_indexing_monitor.value
    assert run.summary["inspected_url_count"] == 4
    assert run.summary["redis_required"] is False


@pytest.mark.asyncio
async def test_run_failure_is_recorded(monkeypatch):
    repo = FakeSchedulerRepository()
    schedule = make_schedule(tenant_id=repo.tenant_id, project_id=repo.project_id)
    service = make_service(repo)

    class FailingPlannerService:
        def __init__(self, db):
            pass

        async def run_project(self, project_id, tenant_id, run_type, target_week_start=None):
            raise RuntimeError("planner exploded")

    monkeypatch.setattr(service, "planner_service_class", FailingPlannerService)

    run = await service.execute_schedule(schedule)

    assert run.status == SeoScheduledRunStatus.failed
    assert "planner exploded" in run.error_message


@pytest.mark.asyncio
async def test_update_recalculates_next_run():
    repo = FakeSchedulerRepository()
    schedule = make_schedule(tenant_id=repo.tenant_id, project_id=repo.project_id)
    repo.schedules.append(schedule)
    service = make_service(repo)
    original = schedule.next_run_at

    updated = await service.update_schedule(
        schedule.id,
        repo.tenant_id,
        SeoScheduleUpdate(hour=22, minute=45),
    )

    assert updated.next_run_at is not None
    assert updated.next_run_at != original
