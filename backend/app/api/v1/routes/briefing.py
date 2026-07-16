"""Daily executive briefing + notification routes."""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.briefing import (
    BriefingHistoryResponse,
    BriefingTrendsResponse,
    DailyBriefingResponse,
    NotificationListResponse,
    NotificationResponse,
)
from app.services.daily_briefing import DailyBriefingService
from app.services.notifications import NotificationService

router = APIRouter()


def _tenant_id(current_user: dict) -> UUID:
    return current_user["tenant_id"]


@router.post("/projects/{project_id}/generate", response_model=DailyBriefingResponse)
async def generate_briefing(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    use_llm: bool = Query(True, description="Use the local LLM for the summary (falls back to template)."),
):
    """Generate (or refresh) today's executive briefing for a project."""
    service = DailyBriefingService(db)
    try:
        return await service.generate(project_id, _tenant_id(current_user), use_llm=use_llm)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/projects/{project_id}/latest", response_model=DailyBriefingResponse)
async def latest_briefing(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = DailyBriefingService(db)
    briefing = await service.get_latest(project_id, _tenant_id(current_user))
    if not briefing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No briefing yet — generate one")
    return briefing


@router.get("/projects/{project_id}/history", response_model=BriefingHistoryResponse)
async def briefing_history(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = Query(30, ge=1, le=365),
):
    service = DailyBriefingService(db)
    items = await service.list_history(project_id, _tenant_id(current_user), days=days)
    return BriefingHistoryResponse(briefings=items, total=len(items))


@router.get("/projects/{project_id}/trends", response_model=BriefingTrendsResponse)
async def briefing_trends(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    window: int = Query(30, ge=7, le=90),
):
    service = DailyBriefingService(db)
    return await service.get_trends(project_id, _tenant_id(current_user), window=window)


@router.get("/notifications", response_model=NotificationListResponse)
async def list_notifications(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: Optional[UUID] = Query(None),
    unread_only: bool = Query(False),
):
    service = NotificationService(db)
    tenant_id = _tenant_id(current_user)
    items = await service.list(tenant_id, project_id=project_id, unread_only=unread_only)
    unread = await service.unread_count(tenant_id, project_id=project_id)
    return NotificationListResponse(notifications=items, unread_count=unread)


@router.post("/notifications/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = NotificationService(db)
    note = await service.mark_read(notification_id, _tenant_id(current_user))
    if not note:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return note
