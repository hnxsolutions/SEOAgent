"""Repository for manual SERP snapshots."""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.serp import SerpSnapshot, SerpSnapshotAsset, SerpSnapshotResult


class SerpSnapshotRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_project(self, project_id: UUID, tenant_id: UUID) -> Optional[Project]:
        result = await self.db.execute(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))
        return result.scalar_one_or_none()

    async def create_snapshot(self, values: dict, results: list[dict]) -> tuple[SerpSnapshot, list[SerpSnapshotResult]]:
        snapshot = SerpSnapshot(**values)
        self.db.add(snapshot)
        await self.db.flush()
        created_results = []
        for result_values in results:
            result = SerpSnapshotResult(snapshot_id=snapshot.id, **result_values)
            self.db.add(result)
            created_results.append(result)
        await self.db.flush()
        await self.db.refresh(snapshot)
        for result in created_results:
            await self.db.refresh(result)
        return snapshot, created_results

    async def list_snapshots(self, project_id: UUID, tenant_id: UUID, limit: int = 100, offset: int = 0):
        result = await self.db.execute(
            select(SerpSnapshot)
            .where(SerpSnapshot.project_id == project_id, SerpSnapshot.tenant_id == tenant_id)
            .order_by(SerpSnapshot.captured_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_snapshot(self, snapshot_id: UUID, tenant_id: UUID):
        result = await self.db.execute(
            select(SerpSnapshot).where(SerpSnapshot.id == snapshot_id, SerpSnapshot.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def results(self, snapshot_id: UUID, tenant_id: UUID):
        result = await self.db.execute(
            select(SerpSnapshotResult)
            .where(SerpSnapshotResult.snapshot_id == snapshot_id, SerpSnapshotResult.tenant_id == tenant_id)
            .order_by(SerpSnapshotResult.position.asc())
        )
        return list(result.scalars().all())

    async def assets(self, snapshot_id: UUID, tenant_id: UUID):
        result = await self.db.execute(
            select(SerpSnapshotAsset)
            .where(SerpSnapshotAsset.snapshot_id == snapshot_id, SerpSnapshotAsset.tenant_id == tenant_id)
            .order_by(SerpSnapshotAsset.created_at.desc())
        )
        return list(result.scalars().all())

    async def previous_snapshot(self, snapshot: SerpSnapshot):
        result = await self.db.execute(
            select(SerpSnapshot)
            .where(
                SerpSnapshot.project_id == snapshot.project_id,
                SerpSnapshot.tenant_id == snapshot.tenant_id,
                SerpSnapshot.keyword == snapshot.keyword,
                SerpSnapshot.country == snapshot.country,
                SerpSnapshot.device == snapshot.device,
                SerpSnapshot.id != snapshot.id,
                SerpSnapshot.captured_at < snapshot.captured_at,
            )
            .order_by(SerpSnapshot.captured_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def add_asset(self, values: dict) -> SerpSnapshotAsset:
        asset = SerpSnapshotAsset(**values)
        self.db.add(asset)
        await self.db.flush()
        await self.db.refresh(asset)
        return asset
