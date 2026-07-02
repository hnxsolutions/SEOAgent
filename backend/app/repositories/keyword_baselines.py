"""Repository for manual keyword baselines."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.keyword_baseline import KeywordBaseline
from app.models.project import Project


class KeywordBaselineRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_project(self, project_id: UUID, tenant_id: UUID) -> Optional[Project]:
        result = await self.db.execute(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))
        return result.scalar_one_or_none()

    async def create(self, values: dict) -> KeywordBaseline:
        baseline = KeywordBaseline(**values)
        self.db.add(baseline)
        await self.db.flush()
        await self.db.refresh(baseline)
        return baseline

    async def bulk_create(self, values: list[dict]) -> list[KeywordBaseline]:
        baselines = [KeywordBaseline(**item) for item in values]
        for baseline in baselines:
            self.db.add(baseline)
        await self.db.flush()
        for baseline in baselines:
            await self.db.refresh(baseline)
        return baselines

    async def list(
        self,
        project_id: UUID,
        tenant_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[KeywordBaseline]:
        result = await self.db.execute(
            select(KeywordBaseline)
            .where(KeywordBaseline.project_id == project_id, KeywordBaseline.tenant_id == tenant_id)
            .order_by(KeywordBaseline.captured_at.desc(), KeywordBaseline.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get(self, baseline_id: UUID, tenant_id: UUID) -> Optional[KeywordBaseline]:
        result = await self.db.execute(
            select(KeywordBaseline).where(KeywordBaseline.id == baseline_id, KeywordBaseline.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def update(self, baseline: KeywordBaseline, values: dict) -> KeywordBaseline:
        for key, value in values.items():
            setattr(baseline, key, value)
        baseline.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(baseline)
        return baseline

    async def delete(self, baseline: KeywordBaseline) -> None:
        await self.db.delete(baseline)
        await self.db.flush()
