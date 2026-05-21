"""Repository layer for production SEO schedules."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blog import BlogPlan
from app.models.project import Project
from app.models.repo_agent import RepoConnection
from app.models.scheduler import SeoSchedule, SeoScheduledRun, SeoScheduledRunStatus


RUNNING_STATUSES = {SeoScheduledRunStatus.queued, SeoScheduledRunStatus.running}


class SchedulerRepository:
    """Persistence for schedules and scheduled execution records."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_project(self, project_id: UUID, tenant_id: UUID) -> Optional[Project]:
        result = await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def create_schedule(self, values: dict) -> SeoSchedule:
        schedule = SeoSchedule(**values)
        self.db.add(schedule)
        await self.db.flush()
        await self.db.refresh(schedule)
        return schedule

    async def get_schedule(self, schedule_id: UUID, tenant_id: Optional[UUID] = None) -> Optional[SeoSchedule]:
        query = select(SeoSchedule).where(SeoSchedule.id == schedule_id)
        if tenant_id:
            query = query.where(SeoSchedule.tenant_id == tenant_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_schedules(
        self,
        project_id: UUID,
        tenant_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> List[SeoSchedule]:
        result = await self.db.execute(
            select(SeoSchedule)
            .where(SeoSchedule.project_id == project_id, SeoSchedule.tenant_id == tenant_id)
            .order_by(SeoSchedule.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_schedule(self, schedule: SeoSchedule, values: dict) -> SeoSchedule:
        for key, value in values.items():
            setattr(schedule, key, value)
        schedule.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(schedule)
        return schedule

    async def due_schedules(
        self,
        now: datetime,
        tenant_id: Optional[UUID] = None,
        limit: int = 50,
    ) -> List[SeoSchedule]:
        query = select(SeoSchedule).where(
            SeoSchedule.is_enabled.is_(True),
            SeoSchedule.next_run_at.is_not(None),
            SeoSchedule.next_run_at <= now,
        )
        if tenant_id:
            query = query.where(SeoSchedule.tenant_id == tenant_id)
        query = query.order_by(SeoSchedule.next_run_at.asc()).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def has_running_run(self, schedule_id: UUID) -> bool:
        result = await self.db.execute(
            select(SeoScheduledRun)
            .where(
                SeoScheduledRun.schedule_id == schedule_id,
                SeoScheduledRun.status.in_(list(RUNNING_STATUSES)),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def create_run(
        self,
        schedule: SeoSchedule,
        status: SeoScheduledRunStatus = SeoScheduledRunStatus.queued,
    ) -> SeoScheduledRun:
        run = SeoScheduledRun(
            tenant_id=schedule.tenant_id,
            project_id=schedule.project_id,
            schedule_id=schedule.id,
            status=status,
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def get_run(self, run_id: UUID, tenant_id: Optional[UUID] = None) -> Optional[SeoScheduledRun]:
        query = select(SeoScheduledRun).where(SeoScheduledRun.id == run_id)
        if tenant_id:
            query = query.where(SeoScheduledRun.tenant_id == tenant_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_runs(
        self,
        schedule_id: UUID,
        tenant_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> List[SeoScheduledRun]:
        result = await self.db.execute(
            select(SeoScheduledRun)
            .where(SeoScheduledRun.schedule_id == schedule_id, SeoScheduledRun.tenant_id == tenant_id)
            .order_by(SeoScheduledRun.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def set_run_status(
        self,
        run: SeoScheduledRun,
        status: SeoScheduledRunStatus,
        error_message: Optional[str] = None,
    ) -> SeoScheduledRun:
        now = datetime.utcnow()
        run.status = status
        run.error_message = error_message
        run.updated_at = now
        if status == SeoScheduledRunStatus.running and not run.started_at:
            run.started_at = now
        if status in {
            SeoScheduledRunStatus.completed,
            SeoScheduledRunStatus.failed,
            SeoScheduledRunStatus.skipped,
        }:
            run.completed_at = now
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def finish_run(
        self,
        run: SeoScheduledRun,
        *,
        status: SeoScheduledRunStatus,
        ids: Optional[dict] = None,
        summary: Optional[dict] = None,
        error_message: Optional[str] = None,
    ) -> SeoScheduledRun:
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
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def mark_schedule_executed(
        self,
        schedule: SeoSchedule,
        *,
        last_run_at: datetime,
        next_run_at: Optional[datetime],
    ) -> SeoSchedule:
        schedule.last_run_at = last_run_at
        schedule.next_run_at = next_run_at
        schedule.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(schedule)
        return schedule

    async def latest_blog_plan(self, project_id: UUID, tenant_id: UUID) -> Optional[BlogPlan]:
        result = await self.db.execute(
            select(BlogPlan)
            .where(BlogPlan.project_id == project_id, BlogPlan.tenant_id == tenant_id)
            .order_by(BlogPlan.updated_at.desc(), BlogPlan.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def first_repo_connection(self, project_id: UUID, tenant_id: UUID) -> Optional[RepoConnection]:
        result = await self.db.execute(
            select(RepoConnection)
            .where(RepoConnection.project_id == project_id, RepoConnection.tenant_id == tenant_id)
            .order_by(RepoConnection.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
