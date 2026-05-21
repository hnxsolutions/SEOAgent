"""GSC average-position rank tracking routes."""
from datetime import date, datetime
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.search_console import GSCComparisonWindow
from app.schemas.rank_tracking import (
    RankTrackingKeywordsResponse,
    RankTrackingListResponse,
    RankTrackingPagesResponse,
    RankTrackingSummaryResponse,
)
from app.services.rank_tracking import RankTrackingService

router = APIRouter()


@router.get("/projects/{project_id}/rankings", response_model=RankTrackingListResponse)
async def project_rankings(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    movement: Optional[str] = Query(None),
    sort: str = Query("highest_impressions"),
    query: Optional[str] = Query(None),
    page_url: Optional[str] = Query(None),
    device: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    comparison_window: Optional[GSCComparisonWindow] = Query(None),
    date_start: Optional[date] = Query(None),
    date_end: Optional[date] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    service = RankTrackingService(db)
    try:
        rows, has_more = await service.rankings(
            project_id,
            _tenant_id(current_user),
            movement=movement,
            sort=sort,
            query=query,
            page_url=page_url,
            device=device,
            country=country,
            comparison_window=comparison_window,
            date_start=_date_to_datetime(date_start),
            date_end=_date_to_datetime(date_end),
            limit=limit,
            offset=offset,
        )
        return RankTrackingListResponse(rankings=rows, limit=limit, offset=offset, has_more=has_more)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/projects/{project_id}/movements", response_model=RankTrackingListResponse)
async def project_movements(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    movement: Optional[str] = Query(None),
    query: Optional[str] = Query(None),
    page_url: Optional[str] = Query(None),
    device: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    comparison_window: Optional[GSCComparisonWindow] = Query(None),
    date_start: Optional[date] = Query(None),
    date_end: Optional[date] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    service = RankTrackingService(db)
    try:
        rows, has_more = await service.movements(
            project_id,
            _tenant_id(current_user),
            movement=movement,
            query=query,
            page_url=page_url,
            device=device,
            country=country,
            comparison_window=comparison_window,
            date_start=_date_to_datetime(date_start),
            date_end=_date_to_datetime(date_end),
            limit=limit,
            offset=offset,
        )
        return RankTrackingListResponse(rankings=rows, limit=limit, offset=offset, has_more=has_more)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/projects/{project_id}/pages", response_model=RankTrackingPagesResponse)
async def project_rank_pages(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    query: Optional[str] = Query(None),
    page_url: Optional[str] = Query(None),
    device: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    comparison_window: Optional[GSCComparisonWindow] = Query(None),
    date_start: Optional[date] = Query(None),
    date_end: Optional[date] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    service = RankTrackingService(db)
    try:
        rows, has_more = await service.pages(
            project_id,
            _tenant_id(current_user),
            query=query,
            page_url=page_url,
            device=device,
            country=country,
            comparison_window=comparison_window,
            date_start=_date_to_datetime(date_start),
            date_end=_date_to_datetime(date_end),
            limit=limit,
            offset=offset,
        )
        return RankTrackingPagesResponse(pages=rows, limit=limit, offset=offset, has_more=has_more)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/projects/{project_id}/keywords", response_model=RankTrackingKeywordsResponse)
async def project_rank_keywords(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    query: Optional[str] = Query(None),
    page_url: Optional[str] = Query(None),
    device: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    comparison_window: Optional[GSCComparisonWindow] = Query(None),
    date_start: Optional[date] = Query(None),
    date_end: Optional[date] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    service = RankTrackingService(db)
    try:
        rows, has_more = await service.keywords(
            project_id,
            _tenant_id(current_user),
            query=query,
            page_url=page_url,
            device=device,
            country=country,
            comparison_window=comparison_window,
            date_start=_date_to_datetime(date_start),
            date_end=_date_to_datetime(date_end),
            limit=limit,
            offset=offset,
        )
        return RankTrackingKeywordsResponse(keywords=rows, limit=limit, offset=offset, has_more=has_more)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/projects/{project_id}/summary", response_model=RankTrackingSummaryResponse)
async def project_rank_summary(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = RankTrackingService(db)
    try:
        return await service.summary(project_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _tenant_id(current_user: dict) -> UUID:
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Authenticated user has no tenant context")
    return tenant_id


def _date_to_datetime(value: Optional[date]) -> Optional[datetime]:
    return datetime.combine(value, datetime.min.time()) if value else None
