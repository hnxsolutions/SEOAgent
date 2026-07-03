"""Production scheduler orchestration for recurring SEO automation."""
from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Dict, List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.models.planner import SeoPlannerRunType
from app.models.scheduler import (
    SeoSchedule,
    SeoScheduledRun,
    SeoScheduledRunStatus,
    SeoScheduleFrequency,
    SeoScheduleType,
)
from app.models.search_console import GSCSyncJobStatus, GSCSyncType
from app.repositories.scheduler import SchedulerRepository
from app.services.blogs import BlogService
from app.services.impact import SeoImpactService
from app.services.indexing import IndexingService
from app.services.planner import PlannerService
from app.services.repo_agent import RepoAgentService
from app.services.search_console import SearchConsoleConfigurationError, SearchConsoleError, SearchConsoleService

logger = structlog.get_logger(__name__)

FIXED_TIMEZONE_FALLBACKS = {
    "UTC": timezone.utc,
    "Etc/UTC": timezone.utc,
    "Asia/Calcutta": timezone(timedelta(hours=5, minutes=30), "Asia/Calcutta"),
    "Asia/Kolkata": timezone(timedelta(hours=5, minutes=30), "Asia/Kolkata"),
}


class SchedulerError(RuntimeError):
    """Raised when a scheduled automation cannot be completed."""


class SchedulerService:
    """Creates and executes recurring SEO automation schedules."""

    search_console_service_class = SearchConsoleService
    planner_service_class = PlannerService
    blog_service_class = BlogService
    repo_agent_service_class = RepoAgentService
    impact_service_class = SeoImpactService
    indexing_service_class = IndexingService

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = SchedulerRepository(db)

    async def create_schedule(self, tenant_id: UUID, payload) -> SeoSchedule:
        project = await self.repository.get_project(payload.project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")
        values = payload.model_dump()
        values["tenant_id"] = tenant_id
        values["name"] = values["name"].strip()
        values["next_run_at"] = self.calculate_next_run(values) if values.get("is_enabled", True) else None
        schedule = await self.repository.create_schedule(values)
        await self.db.commit()
        await self.db.refresh(schedule)
        return schedule

    async def list_schedules(self, project_id: UUID, tenant_id: UUID, limit: int = 100, offset: int = 0) -> List[SeoSchedule]:
        return await self.repository.list_schedules(project_id, tenant_id, limit=limit, offset=offset)

    async def get_schedule(self, schedule_id: UUID, tenant_id: UUID) -> Optional[SeoSchedule]:
        return await self.repository.get_schedule(schedule_id, tenant_id)

    async def update_schedule(self, schedule_id: UUID, tenant_id: UUID, payload) -> SeoSchedule:
        schedule = await self.repository.get_schedule(schedule_id, tenant_id)
        if not schedule:
            raise ValueError("Schedule not found")
        values = payload.model_dump(exclude_unset=True)
        if "name" in values and values["name"]:
            values["name"] = values["name"].strip()
        merged = self._schedule_values(schedule)
        merged.update(values)
        is_enabled = bool(merged.get("is_enabled"))
        values["next_run_at"] = self.calculate_next_run(merged) if is_enabled else None
        schedule = await self.repository.update_schedule(schedule, values)
        await self.db.commit()
        await self.db.refresh(schedule)
        return schedule

    async def enable_schedule(self, schedule_id: UUID, tenant_id: UUID) -> SeoSchedule:
        schedule = await self.repository.get_schedule(schedule_id, tenant_id)
        if not schedule:
            raise ValueError("Schedule not found")
        values = self._schedule_values(schedule)
        values["is_enabled"] = True
        schedule = await self.repository.update_schedule(
            schedule,
            {"is_enabled": True, "next_run_at": self.calculate_next_run(values)},
        )
        await self.db.commit()
        await self.db.refresh(schedule)
        return schedule

    async def disable_schedule(self, schedule_id: UUID, tenant_id: UUID) -> SeoSchedule:
        schedule = await self.repository.get_schedule(schedule_id, tenant_id)
        if not schedule:
            raise ValueError("Schedule not found")
        schedule = await self.repository.update_schedule(schedule, {"is_enabled": False, "next_run_at": None})
        await self.db.commit()
        await self.db.refresh(schedule)
        return schedule

    async def run_now(self, schedule_id: UUID, tenant_id: UUID) -> SeoScheduledRun:
        schedule = await self.repository.get_schedule(schedule_id, tenant_id)
        if not schedule:
            raise ValueError("Schedule not found")
        return await self.execute_schedule(schedule, manual_trigger=True)

    async def tick(
        self,
        tenant_id: Optional[UUID] = None,
        now: Optional[datetime] = None,
        limit: int = 50,
    ) -> List[SeoScheduledRun]:
        await self._evaluate_ready_impact_experiments(now=now)
        await self._run_due_gsc_monitors(tenant_id=tenant_id, now=now, limit=limit)
        due = await self.repository.due_schedules(self._naive_utc(now), tenant_id=tenant_id, limit=limit)
        runs = []
        for schedule in due:
            runs.append(await self.execute_schedule(schedule, manual_trigger=False))
        return runs

    async def _run_due_gsc_monitors(
        self,
        tenant_id: Optional[UUID] = None,
        now: Optional[datetime] = None,
        limit: int = 50,
    ) -> None:
        try:
            await self.search_console_service_class(self.db).run_due_monitor_syncs(
                tenant_id=tenant_id,
                now=self._naive_utc(now),
                limit=limit,
            )
        except Exception as exc:
            logger.warning("Scheduled GSC monitor check failed", error=str(exc))

    async def _evaluate_ready_impact_experiments(self, now: Optional[datetime] = None) -> None:
        try:
            await self.impact_service_class(self.db).evaluate_ready_experiments(now=self._naive_utc(now))
        except Exception as exc:
            logger.warning("Impact experiment scheduled review check failed", error=str(exc))

    async def get_run_status(self, run_id: UUID, tenant_id: UUID) -> Optional[SeoScheduledRun]:
        return await self.repository.get_run(run_id, tenant_id)

    async def list_runs(
        self,
        schedule_id: UUID,
        tenant_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> List[SeoScheduledRun]:
        schedule = await self.repository.get_schedule(schedule_id, tenant_id)
        if not schedule:
            raise ValueError("Schedule not found")
        return await self.repository.list_runs(schedule_id, tenant_id, limit=limit, offset=offset)

    async def execute_schedule(self, schedule: SeoSchedule, manual_trigger: bool = False) -> SeoScheduledRun:
        if await self.repository.has_running_run(schedule.id):
            run = await self.repository.create_run(schedule, status=SeoScheduledRunStatus.skipped)
            run = await self.repository.finish_run(
                run,
                status=SeoScheduledRunStatus.skipped,
                summary={"reason": "A run for this schedule is already queued or running."},
                error_message="Schedule already has a running execution.",
            )
            await self.db.commit()
            await self.db.refresh(run)
            return run

        run = await self.repository.create_run(schedule)
        await self.repository.set_run_status(run, SeoScheduledRunStatus.running)
        await self.db.commit()
        try:
            result = await self._execute_schedule_type(schedule)
            status = result.get("status", SeoScheduledRunStatus.completed)
            ids = result.get("ids", {})
            summary = result.get("summary", {})
            error_message = result.get("error_message")
            run = await self.repository.finish_run(
                run,
                status=status,
                ids=ids,
                summary=summary,
                error_message=error_message,
            )
            if not manual_trigger:
                await self.repository.mark_schedule_executed(
                    schedule,
                    last_run_at=run.completed_at or self._naive_utc(),
                    next_run_at=self.calculate_next_run(schedule, after=run.completed_at or self._naive_utc()),
                )
            await self.db.commit()
            await self.db.refresh(run)
            return run
        except Exception as exc:
            run = await self.repository.finish_run(
                run,
                status=SeoScheduledRunStatus.failed,
                summary={"schedule_type": self._enum_value(schedule.schedule_type)},
                error_message=str(exc),
            )
            if not manual_trigger:
                await self.repository.mark_schedule_executed(
                    schedule,
                    last_run_at=run.completed_at or self._naive_utc(),
                    next_run_at=self.calculate_next_run(schedule, after=run.completed_at or self._naive_utc()),
                )
            await self.db.commit()
            logger.error("Scheduled SEO run failed", schedule_id=str(schedule.id), run_id=str(run.id), error=str(exc), exc_info=True)
            return run

    async def _execute_schedule_type(self, schedule: SeoSchedule) -> dict:
        schedule_type = self._enum_value(schedule.schedule_type)
        if schedule_type == SeoScheduleType.daily_gsc_sync.value:
            return await self._run_gsc_sync(schedule)
        if schedule_type in {SeoScheduleType.weekly_full_seo.value, SeoScheduleType.monthly_deep_audit.value}:
            return await self._run_planner(schedule, monthly=schedule_type == SeoScheduleType.monthly_deep_audit.value)
        if schedule_type == SeoScheduleType.weekly_blog_planning.value:
            return await self._run_blog_planning(schedule)
        if schedule_type == SeoScheduleType.weekly_repo_scan.value:
            return await self._run_repo_scan(schedule)
        if schedule_type == SeoScheduleType.weekly_indexing_monitor.value:
            return await self._run_indexing_monitor(schedule)
        raise SchedulerError(f"Unsupported schedule type: {schedule_type}")

    async def _run_gsc_sync(self, schedule: SeoSchedule) -> dict:
        service = self.search_console_service_class(self.db)
        try:
            job = await service.sync_project(
                tenant_id=schedule.tenant_id,
                project_id=schedule.project_id,
                sync_type=GSCSyncType.scheduled,
            )
        except SearchConsoleConfigurationError as exc:
            return {
                "status": SeoScheduledRunStatus.skipped,
                "summary": {
                    "schedule_type": SeoScheduleType.daily_gsc_sync.value,
                    "reason": "OAuth credentials are not configured.",
                },
                "error_message": str(exc),
            }
        except (SearchConsoleError, ValueError) as exc:
            message = str(exc)
            if "OAuth connection required" in message or "No selected Search Console property" in message:
                return {
                    "status": SeoScheduledRunStatus.skipped,
                    "summary": {"schedule_type": SeoScheduleType.daily_gsc_sync.value, "reason": message},
                    "error_message": message,
                }
            raise

        status = SeoScheduledRunStatus.completed
        message = None
        if self._enum_value(job.status) == GSCSyncJobStatus.failed.value:
            message = job.error_message or "GSC sync failed."
            status = (
                SeoScheduledRunStatus.skipped
                if "OAuth connection required" in message or "CSV fallback" in message
                else SeoScheduledRunStatus.failed
            )
        return {
            "status": status,
            "ids": {"gsc_sync_job_id": job.id},
            "summary": {
                "schedule_type": SeoScheduleType.daily_gsc_sync.value,
                "gsc_sync_status": self._enum_value(job.status),
                "rows_fetched": int(getattr(job, "rows_fetched", 0) or 0),
                "opportunities_created": int(getattr(job, "opportunities_created", 0) or 0),
                "opportunities_updated": int(getattr(job, "opportunities_updated", 0) or 0),
            },
            "error_message": message if status != SeoScheduledRunStatus.completed else None,
        }

    async def _run_planner(self, schedule: SeoSchedule, monthly: bool = False) -> dict:
        preflight: Dict[str, Any] = {}
        preflight_ids: Dict[str, UUID] = {}
        if not monthly:
            try:
                gsc_result = await self._run_gsc_sync(schedule)
                preflight["gsc_sync"] = gsc_result.get("summary", {})
                preflight_ids.update(gsc_result.get("ids", {}))
            except Exception as exc:
                preflight["gsc_sync"] = {"status": "failed", "error": str(exc)}
            try:
                repo_result = await self._run_repo_scan(schedule)
                preflight["repo_scan"] = repo_result.get("summary", {})
                preflight_ids.update(repo_result.get("ids", {}))
            except Exception as exc:
                preflight["repo_scan"] = {"status": "failed", "error": str(exc)}
        service = self.planner_service_class(self.db)
        planner_run = await service.run_project(
            schedule.project_id,
            schedule.tenant_id,
            run_type=SeoPlannerRunType.scheduled,
        )
        return {
            "status": SeoScheduledRunStatus.completed,
            "ids": {
                "planner_run_id": planner_run.id,
                "crawl_id": planner_run.crawl_id,
                "audit_id": planner_run.audit_id,
                "semantic_run_id": planner_run.semantic_run_id,
                "gsc_sync_job_id": planner_run.gsc_sync_job_id or preflight_ids.get("gsc_sync_job_id"),
                "repo_scan_run_id": planner_run.repo_scan_run_id or preflight_ids.get("repo_scan_run_id"),
                "blog_plan_id": planner_run.blog_plan_id,
            },
            "summary": {
                "schedule_type": (
                    SeoScheduleType.monthly_deep_audit.value if monthly else SeoScheduleType.weekly_full_seo.value
                ),
                "planner_run_status": self._enum_value(planner_run.status),
                "tasks_created": int(getattr(planner_run, "tasks_created", 0) or 0),
                "high_priority_tasks": int(getattr(planner_run, "high_priority_tasks", 0) or 0),
                "preflight": preflight,
                "safety": "Generated recommendations, tasks, and reports only. No publishing, patch apply, PR, merge, or deploy actions were run.",
            },
        }

    async def _run_blog_planning(self, schedule: SeoSchedule) -> dict:
        project = await self.repository.get_project(schedule.project_id, schedule.tenant_id)
        if not project:
            raise ValueError("Project not found")
        service = self.blog_service_class(self.db)
        plan = await self.repository.latest_blog_plan(schedule.project_id, schedule.tenant_id)
        if not plan:
            plan = await service.create_plan(
                tenant_id=schedule.tenant_id,
                project_id=schedule.project_id,
                title=f"Weekly blog plan for {project.name}",
                description="Recurring buyer-intent blog planning generated by the SEO scheduler.",
                target_site_url=project.domain,
                blogs_per_week=3,
            )
        topics = await service.generate_topics(plan.id, schedule.tenant_id, count=getattr(plan, "blogs_per_week", 3) or 3)
        return {
            "status": SeoScheduledRunStatus.completed,
            "ids": {"blog_plan_id": plan.id},
            "summary": {
                "schedule_type": SeoScheduleType.weekly_blog_planning.value,
                "topics_created_or_returned": len(topics),
                "blog_plan_id": str(plan.id),
                "safety": "Topics only. Draft publishing is not automatic.",
            },
        }

    async def _run_repo_scan(self, schedule: SeoSchedule) -> dict:
        connection = await self.repository.first_repo_connection(schedule.project_id, schedule.tenant_id)
        if not connection:
            return {
                "status": SeoScheduledRunStatus.skipped,
                "summary": {
                    "schedule_type": SeoScheduleType.weekly_repo_scan.value,
                    "reason": "No repository connection is configured for this project.",
                },
                "error_message": "No repository connection configured.",
            }
        service = self.repo_agent_service_class(self.db)
        scan = await service.scan_connection(connection.id, schedule.tenant_id)
        patches = await service.generate_patches(scan.id, schedule.tenant_id)
        return {
            "status": SeoScheduledRunStatus.completed,
            "ids": {"repo_scan_run_id": scan.id},
            "summary": {
                "schedule_type": SeoScheduleType.weekly_repo_scan.value,
                "repo_connection_id": str(connection.id),
                "files_scanned": int(getattr(scan, "files_scanned", 0) or 0),
                "issues_found": int(getattr(scan, "issues_found", 0) or 0),
                "patches_proposed": len(patches),
                "safety": "Patch proposals only. No patches were applied and no PRs were created.",
            },
        }

    async def _run_indexing_monitor(self, schedule: SeoSchedule) -> dict:
        service = self.indexing_service_class(self.db)
        try:
            summary = await service.run_weekly_monitor(schedule.project_id, schedule.tenant_id)
        except (SearchConsoleConfigurationError, SearchConsoleError, ValueError) as exc:
            message = str(exc)
            if "OAuth" in message or "No selected Search Console property" in message:
                return {
                    "status": SeoScheduledRunStatus.skipped,
                    "summary": {
                        "schedule_type": SeoScheduleType.weekly_indexing_monitor.value,
                        "reason": message,
                        "redis_required": False,
                    },
                    "error_message": message,
                }
            raise
        return {
            "status": SeoScheduledRunStatus.completed,
            "summary": {
                "schedule_type": SeoScheduleType.weekly_indexing_monitor.value,
                **summary,
                "safety": "GSC sync, URL inspection, issue classification, tasks, and reports only. No patches were applied and no PRs, merges, deploys, or publishing actions were run.",
                "redis_required": False,
            },
        }

    def calculate_next_run(self, schedule_or_values, after: Optional[datetime] = None) -> datetime:
        values = self._schedule_values(schedule_or_values)
        frequency = SeoScheduleFrequency(self._enum_value(values["frequency"]))
        local_tz = self._timezone(values.get("timezone") or "UTC")
        after_utc = self._aware_utc(after)
        local_after = after_utc.astimezone(local_tz)
        hour = int(values.get("hour", 9))
        minute = int(values.get("minute", 0))

        if frequency == SeoScheduleFrequency.daily:
            candidate = local_after.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= local_after:
                candidate += timedelta(days=1)
            return self._to_naive_utc(candidate)

        if frequency == SeoScheduleFrequency.weekly:
            day = values.get("day_of_week")
            day = int(day) if day is not None else local_after.weekday()
            delta_days = (day - local_after.weekday()) % 7
            candidate_date = local_after.date() + timedelta(days=delta_days)
            candidate = datetime.combine(candidate_date, datetime.min.time(), tzinfo=local_tz).replace(hour=hour, minute=minute)
            if candidate <= local_after:
                candidate += timedelta(days=7)
            return self._to_naive_utc(candidate)

        day = int(values.get("day_of_month") or 1)
        year, month = local_after.year, local_after.month
        candidate = self._monthly_candidate(year, month, day, hour, minute, local_tz)
        if candidate <= local_after:
            year, month = self._next_month(year, month)
            candidate = self._monthly_candidate(year, month, day, hour, minute, local_tz)
        return self._to_naive_utc(candidate)

    def _monthly_candidate(self, year: int, month: int, day: int, hour: int, minute: int, tz: tzinfo) -> datetime:
        safe_day = min(max(day, 1), monthrange(year, month)[1])
        return datetime(year, month, safe_day, hour, minute, tzinfo=tz)

    def _next_month(self, year: int, month: int) -> tuple[int, int]:
        if month == 12:
            return year + 1, 1
        return year, month + 1

    def _schedule_values(self, schedule_or_values) -> Dict[str, Any]:
        if isinstance(schedule_or_values, dict):
            return dict(schedule_or_values)
        return {
            "schedule_type": schedule_or_values.schedule_type,
            "frequency": schedule_or_values.frequency,
            "day_of_week": schedule_or_values.day_of_week,
            "day_of_month": schedule_or_values.day_of_month,
            "hour": schedule_or_values.hour,
            "minute": schedule_or_values.minute,
            "timezone": schedule_or_values.timezone,
            "is_enabled": schedule_or_values.is_enabled,
        }

    def _timezone(self, name: str) -> tzinfo:
        if name in FIXED_TIMEZONE_FALLBACKS:
            return FIXED_TIMEZONE_FALLBACKS[name]
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown timezone: {name}") from exc

    def _aware_utc(self, value: Optional[datetime] = None) -> datetime:
        value = value or datetime.utcnow()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _naive_utc(self, value: Optional[datetime] = None) -> datetime:
        return self._aware_utc(value).replace(tzinfo=None)

    def _to_naive_utc(self, value: datetime) -> datetime:
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def _enum_value(self, value) -> str:
        return getattr(value, "value", value)
