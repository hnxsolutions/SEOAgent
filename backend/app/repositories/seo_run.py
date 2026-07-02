"""Repository layer for one-click SEO runs."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.seo_run import SeoRun, SeoRunStage, SeoRunStageStatus, SeoRunStatus


SEO_RUN_STAGES = [
    SeoRunStage.crawl,
    SeoRunStage.audit,
    SeoRunStage.semantic_index,
    SeoRunStage.content_optimization,
    SeoRunStage.planner,
]


class SeoRunRepository:
    """Persistence helpers for top-level SEO run orchestration."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_project(self, project_id: UUID, tenant_id: UUID) -> Optional[Project]:
        result = await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def create_run(self, project: Project, tenant_id: UUID) -> SeoRun:
        run = SeoRun(
            tenant_id=tenant_id,
            project_id=project.id,
            status=SeoRunStatus.queued,
            current_stage=SeoRunStage.crawl,
            stage_statuses={stage.value: SeoRunStageStatus.pending.value for stage in SEO_RUN_STAGES},
            stage_errors={},
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def get_run(self, run_id: UUID, tenant_id: Optional[UUID] = None) -> Optional[SeoRun]:
        query = select(SeoRun).where(SeoRun.id == run_id)
        if tenant_id:
            query = query.where(SeoRun.tenant_id == tenant_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_runs(
        self,
        project_id: UUID,
        tenant_id: UUID,
        limit: int = 25,
        offset: int = 0,
    ) -> List[SeoRun]:
        result = await self.db.execute(
            select(SeoRun)
            .where(SeoRun.project_id == project_id, SeoRun.tenant_id == tenant_id)
            .order_by(SeoRun.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def set_status(
        self,
        run: SeoRun,
        status: SeoRunStatus,
        *,
        current_stage: Optional[SeoRunStage] = None,
        error_message: Optional[str] = None,
    ) -> SeoRun:
        await self.db.refresh(run)
        now = datetime.utcnow()
        run.status = status
        run.updated_at = now
        if current_stage:
            run.current_stage = current_stage
        if error_message is not None:
            run.error_message = error_message
        if status == SeoRunStatus.running and not run.started_at:
            run.started_at = now
        if status in {SeoRunStatus.completed, SeoRunStatus.failed}:
            run.completed_at = now
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def set_stage(
        self,
        run: SeoRun,
        stage: SeoRunStage,
        stage_status: SeoRunStageStatus,
        *,
        error_message: Optional[str] = None,
    ) -> SeoRun:
        await self.db.refresh(run)
        run.current_stage = stage
        statuses: Dict[str, str] = dict(run.stage_statuses or {})
        statuses[stage.value] = stage_status.value
        run.stage_statuses = statuses

        errors: Dict[str, str] = dict(run.stage_errors or {})
        if error_message:
            errors[stage.value] = error_message
        run.stage_errors = errors
        run.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def attach_ids(self, run: SeoRun, **ids: Optional[UUID]) -> SeoRun:
        fields = set(SeoRun.__table__.columns.keys())
        for field_name, value in ids.items():
            if value is not None and field_name in fields:
                setattr(run, field_name, value)
        run.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(run)
        return run
