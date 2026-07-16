"""Notification engine (dashboard).

Dashboard notifications are always available. Email / Slack / webhook delivery is
future work and credential-gated; when those channels are unconfigured the engine
degrades gracefully to dashboard-only without error.
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.briefing import Notification, NotificationLevel


class NotificationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        tenant_id: UUID,
        level: NotificationLevel,
        title: str,
        message: str,
        *,
        project_id: Optional[UUID] = None,
        category: str = "general",
        dedupe_key: Optional[str] = None,
        commit: bool = True,
    ) -> Optional[Notification]:
        """Create a notification, skipping if an unread one with the same
        dedupe_key already exists (avoids repeat daily alerts)."""
        if dedupe_key:
            existing = (await self.db.execute(
                select(Notification).where(
                    Notification.tenant_id == tenant_id,
                    Notification.dedupe_key == dedupe_key,
                    Notification.read.is_(False),
                )
            )).scalars().first()
            if existing:
                return existing
        note = Notification(
            tenant_id=tenant_id,
            project_id=project_id,
            level=level,
            category=category,
            title=title[:255],
            message=message,
            dedupe_key=dedupe_key,
        )
        self.db.add(note)
        if commit:
            await self.db.commit()
            await self.db.refresh(note)
        return note

    async def list(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        unread_only: bool = False,
        limit: int = 50,
    ) -> List[Notification]:
        query = select(Notification).where(Notification.tenant_id == tenant_id)
        if project_id:
            query = query.where(Notification.project_id == project_id)
        if unread_only:
            query = query.where(Notification.read.is_(False))
        result = await self.db.execute(query.order_by(Notification.created_at.desc()).limit(limit))
        return list(result.scalars().all())

    async def unread_count(self, tenant_id: UUID, project_id: Optional[UUID] = None) -> int:
        query = select(func.count(Notification.id)).where(
            Notification.tenant_id == tenant_id, Notification.read.is_(False)
        )
        if project_id:
            query = query.where(Notification.project_id == project_id)
        return int((await self.db.execute(query)).scalar() or 0)

    async def mark_read(self, notification_id: UUID, tenant_id: UUID) -> Optional[Notification]:
        note = (await self.db.execute(
            select(Notification).where(
                Notification.id == notification_id, Notification.tenant_id == tenant_id
            )
        )).scalars().first()
        if not note:
            return None
        note.read = True
        await self.db.commit()
        await self.db.refresh(note)
        return note
