"""Repository layer for SEO impact tracking."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.impact import (
    SeoImpactExperiment,
    SeoImpactExperimentStatus,
    SeoImpactResult,
    SeoImpactSnapshot,
    SeoImpactSnapshotType,
)
from app.models.project import Project
from app.models.search_console import SearchConsoleRow


class SeoImpactRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_project(self, project_id: UUID, tenant_id: UUID) -> Optional[Project]:
        result = await self.db.execute(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))
        return result.scalar_one_or_none()

    async def create_experiment(self, values: dict) -> SeoImpactExperiment:
        experiment = SeoImpactExperiment(**values)
        self.db.add(experiment)
        await self.db.flush()
        await self.db.refresh(experiment)
        return experiment

    async def list_experiments(self, project_id: UUID, tenant_id: UUID, limit: int = 100, offset: int = 0):
        result = await self.db.execute(
            select(SeoImpactExperiment)
            .where(SeoImpactExperiment.project_id == project_id, SeoImpactExperiment.tenant_id == tenant_id)
            .order_by(SeoImpactExperiment.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_experiment(self, experiment_id: UUID, tenant_id: UUID) -> Optional[SeoImpactExperiment]:
        result = await self.db.execute(
            select(SeoImpactExperiment).where(
                SeoImpactExperiment.id == experiment_id,
                SeoImpactExperiment.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def set_status(self, experiment: SeoImpactExperiment, status: SeoImpactExperimentStatus) -> SeoImpactExperiment:
        experiment.status = status
        experiment.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(experiment)
        return experiment

    async def update_experiment(self, experiment: SeoImpactExperiment, values: dict) -> SeoImpactExperiment:
        for key, value in values.items():
            setattr(experiment, key, value)
        experiment.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(experiment)
        return experiment

    async def rows_for_window(
        self,
        experiment: SeoImpactExperiment,
        date_start: datetime,
        date_end: datetime,
    ) -> list[SearchConsoleRow]:
        stmt = select(SearchConsoleRow).where(
            SearchConsoleRow.tenant_id == experiment.tenant_id,
            SearchConsoleRow.project_id == experiment.project_id,
            SearchConsoleRow.page_url == experiment.target_page_url,
            SearchConsoleRow.date_end >= date_start,
            SearchConsoleRow.date_start <= date_end,
        )
        if experiment.target_query:
            stmt = stmt.where(SearchConsoleRow.query.ilike(experiment.target_query))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create_snapshot(self, values: dict) -> SeoImpactSnapshot:
        snapshot = SeoImpactSnapshot(**values)
        self.db.add(snapshot)
        await self.db.flush()
        await self.db.refresh(snapshot)
        return snapshot

    async def latest_snapshot(
        self,
        experiment_id: UUID,
        snapshot_type: SeoImpactSnapshotType,
    ) -> Optional[SeoImpactSnapshot]:
        result = await self.db.execute(
            select(SeoImpactSnapshot)
            .where(
                SeoImpactSnapshot.experiment_id == experiment_id,
                SeoImpactSnapshot.snapshot_type == snapshot_type,
            )
            .order_by(SeoImpactSnapshot.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_result(self, values: dict) -> SeoImpactResult:
        result = SeoImpactResult(**values)
        self.db.add(result)
        await self.db.flush()
        await self.db.refresh(result)
        return result

    async def list_results(self, project_id: UUID, tenant_id: UUID):
        result = await self.db.execute(
            select(SeoImpactResult).where(SeoImpactResult.project_id == project_id, SeoImpactResult.tenant_id == tenant_id)
        )
        return list(result.scalars().all())

    async def ready_for_review(self, now: datetime, limit: int = 100):
        result = await self.db.execute(
            select(SeoImpactExperiment)
            .where(
                SeoImpactExperiment.status == SeoImpactExperimentStatus.monitoring,
                SeoImpactExperiment.review_end_date.is_not(None),
                SeoImpactExperiment.review_end_date <= now,
            )
            .limit(limit)
        )
        return list(result.scalars().all())
