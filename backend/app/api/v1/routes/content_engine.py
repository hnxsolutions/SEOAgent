"""Content engine and schedule provisioning endpoints.

Everything here is a manual trigger for something the scheduler already does on
its own. They exist so an operator can run a scan now rather than wait for
Monday, and so a project created before autonomous provisioning can be repaired
without touching the database.
"""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.core.database import get_db
from app.services.content_engine import ContentEngineService
from app.services.schedule_provisioning import (
    MAX_BLOGS_PER_WEEK,
    ScheduleProvisioningService,
)

router = APIRouter()


def _tenant_id(current_user: dict) -> UUID:
    return current_user["tenant_id"]


@router.post("/projects/{project_id}/provision-schedules")
async def provision_schedules(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    blogs_per_week: int = Query(2, ge=0, le=MAX_BLOGS_PER_WEEK),
):
    """Create any missing recurring schedules. Safe to call repeatedly."""
    return await ScheduleProvisioningService(db).provision(
        project_id, _tenant_id(current_user), blogs_per_week=blogs_per_week
    )


@router.put("/projects/{project_id}/blogs-per-week")
async def set_blogs_per_week(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    count: int = Query(..., ge=0, le=MAX_BLOGS_PER_WEEK),
):
    """Change the drafting cadence. Extra slots are disabled, never deleted."""
    return await ScheduleProvisioningService(db).set_blogs_per_week(
        project_id, _tenant_id(current_user), count
    )


@router.post("/projects/{project_id}/scan-opportunities")
async def scan_opportunities(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(15, ge=1, le=50),
):
    """Rank free first-party signals into reviewable topics."""
    return await ContentEngineService(db).scan_opportunities(
        project_id, _tenant_id(current_user), limit=limit
    )


@router.post("/projects/{project_id}/draft-next")
async def draft_next(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Draft the best waiting topic, or report why the slot was skipped."""
    return await ContentEngineService(db).draft_next(project_id, _tenant_id(current_user))


@router.get("/drafts/{draft_id}/validation")
async def validate_draft(
    draft_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """SEO and AEO scores for a draft, with the specific failures listed."""
    result = await ContentEngineService(db).validate_draft(draft_id, _tenant_id(current_user))
    if result.get("seo_score") is None and "Draft not found." in (result.get("issues") or []):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    return result


@router.get("/projects/{project_id}/content-performance")
async def content_performance(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Measured performance of published articles, plus refresh proposals."""
    return await ContentEngineService(db).review_performance(project_id, _tenant_id(current_user))
