"""Manual keyword baseline service."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.keyword_baselines import KeywordBaselineRepository
from app.schemas.keyword_baselines import KeywordBaselineBulkRequest, KeywordBaselineCreate, KeywordBaselineUpdate


class KeywordBaselineService:
    """Create and maintain manually entered keyword baseline data."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = KeywordBaselineRepository(db)

    async def create(self, project_id: UUID, tenant_id: UUID, payload: KeywordBaselineCreate):
        await self._ensure_project(project_id, tenant_id)
        baseline = await self.repository.create(self._create_values(project_id, tenant_id, payload))
        await self.db.commit()
        await self.db.refresh(baseline)
        return baseline

    async def list(self, project_id: UUID, tenant_id: UUID, limit: int = 100, offset: int = 0):
        await self._ensure_project(project_id, tenant_id)
        return await self.repository.list(project_id, tenant_id, limit=limit, offset=offset)

    async def update(self, baseline_id: UUID, tenant_id: UUID, payload: KeywordBaselineUpdate):
        baseline = await self.repository.get(baseline_id, tenant_id)
        if not baseline:
            raise ValueError("Keyword baseline not found")
        values = payload.model_dump(exclude_unset=True)
        if "search_engine" in values and values["search_engine"] is not None:
            values["search_engine"] = values["search_engine"].strip().lower()
        if values:
            baseline = await self.repository.update(baseline, values)
            await self.db.commit()
            await self.db.refresh(baseline)
        return baseline

    async def delete(self, baseline_id: UUID, tenant_id: UUID) -> None:
        baseline = await self.repository.get(baseline_id, tenant_id)
        if not baseline:
            raise ValueError("Keyword baseline not found")
        await self.repository.delete(baseline)
        await self.db.commit()

    async def bulk_create(self, project_id: UUID, tenant_id: UUID, payload: KeywordBaselineBulkRequest):
        await self._ensure_project(project_id, tenant_id)
        values = [self._create_values(project_id, tenant_id, item) for item in payload.items]
        baselines = await self.repository.bulk_create(values)
        await self.db.commit()
        for baseline in baselines:
            await self.db.refresh(baseline)
        return baselines

    async def _ensure_project(self, project_id: UUID, tenant_id: UUID) -> None:
        project = await self.repository.get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")

    def _create_values(self, project_id: UUID, tenant_id: UUID, payload: KeywordBaselineCreate) -> dict:
        values = payload.model_dump(exclude_unset=True)
        values["tenant_id"] = tenant_id
        values["project_id"] = project_id
        values["keyword"] = values["keyword"].strip()
        values["search_engine"] = values.get("search_engine", "google").strip().lower() or "google"
        values["captured_at"] = values.get("captured_at") or datetime.utcnow()
        return values
