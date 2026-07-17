"""Core Web Vitals / PageSpeed Insights routes."""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.pagespeed import (
    PagespeedAnalyzeResponse,
    PagespeedHistoryResponse,
    PagespeedLatestResponse,
)
from app.services.pagespeed import PagespeedService

router = APIRouter()


def _tenant_id(current_user: dict) -> UUID:
    return current_user["tenant_id"]


@router.post("/projects/{project_id}/analyze", response_model=PagespeedAnalyzeResponse)
async def analyze_pagespeed(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Run the official PageSpeed Insights API for the project (mobile + desktop)
    and store the results. Degrades honestly (quota_exceeded) without an API key."""
    service = PagespeedService(db)
    try:
        runs = await service.analyze_project(project_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return PagespeedAnalyzeResponse(runs=runs)


@router.get("/projects/{project_id}/latest", response_model=PagespeedLatestResponse)
async def latest_pagespeed(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    latest = await PagespeedService(db).latest(project_id, _tenant_id(current_user))
    return PagespeedLatestResponse(mobile=latest["mobile"], desktop=latest["desktop"])


@router.get("/projects/{project_id}/history", response_model=PagespeedHistoryResponse)
async def pagespeed_history(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    strategy: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    runs = await PagespeedService(db).history(project_id, _tenant_id(current_user), strategy=strategy, limit=limit)
    return PagespeedHistoryResponse(runs=runs, total=len(runs))
