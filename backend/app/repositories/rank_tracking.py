"""Repository helpers for GSC rank tracking."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.search_console import SearchConsoleRow


class RankTrackingRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_project(self, project_id: UUID, tenant_id: UUID) -> Optional[Project]:
        result = await self.db.execute(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))
        return result.scalar_one_or_none()

    async def list_rows(
        self,
        project_id: UUID,
        tenant_id: UUID,
        *,
        date_start: Optional[datetime] = None,
        date_end: Optional[datetime] = None,
        device: Optional[str] = None,
        country: Optional[str] = None,
        query: Optional[str] = None,
        page_url: Optional[str] = None,
    ) -> list[SearchConsoleRow]:
        stmt = select(SearchConsoleRow).where(
            SearchConsoleRow.project_id == project_id,
            SearchConsoleRow.tenant_id == tenant_id,
        )
        if date_start:
            stmt = stmt.where(SearchConsoleRow.date_end >= date_start)
        if date_end:
            stmt = stmt.where(SearchConsoleRow.date_start <= date_end)
        if device:
            stmt = stmt.where(SearchConsoleRow.device == device)
        if country:
            stmt = stmt.where(SearchConsoleRow.country == country)
        if query:
            stmt = stmt.where(SearchConsoleRow.query.ilike(f"%{query}%"))
        if page_url:
            stmt = stmt.where(SearchConsoleRow.page_url.ilike(f"%{page_url}%"))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
