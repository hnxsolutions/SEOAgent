"""GEO/AEO scoring API routes."""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, get_db_session
from app.core.security import get_current_user
from app.models.geo_aeo import GeoAeoRecommendationStatus, GeoAeoRecommendationType
from app.schemas.geo_aeo import (
    GeoAeoPageScoreResponse,
    GeoAeoRecommendationListResponse,
    GeoAeoRecommendationResponse,
    GeoAeoRunResponse,
    GeoAeoSummaryResponse,
)
from app.services.geo_aeo import GeoAeoService

router = APIRouter()


@router.post(
    "/crawls/{crawl_id}/analyze",
    response_model=GeoAeoRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyze_crawl_geo_aeo(
    crawl_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Start GEO/AEO scoring for a completed crawl."""
    service = GeoAeoService(db)
    try:
        run = await service.start_analysis(crawl_id, current_user["tenant_id"])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    background_tasks.add_task(run_geo_aeo_background, run.id)
    return run


@router.get("/runs/{run_id}/status", response_model=GeoAeoRunResponse)
async def get_geo_aeo_run_status(
    run_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get GEO/AEO run status."""
    service = GeoAeoService(db)
    run = await service.get_run_status(run_id, current_user["tenant_id"])
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GEO/AEO run not found")
    return run


@router.get("/crawls/{crawl_id}/summary", response_model=GeoAeoSummaryResponse)
async def get_geo_aeo_summary(
    crawl_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get crawl-level GEO/AEO summary."""
    service = GeoAeoService(db)
    try:
        return await service.summary(crawl_id, current_user["tenant_id"])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/pages/{page_id}/score", response_model=GeoAeoPageScoreResponse)
async def get_geo_aeo_page_score(
    page_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get latest GEO/AEO score for a page."""
    service = GeoAeoService(db)
    page_score = await service.get_page_score(page_id, current_user["tenant_id"])
    if not page_score:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GEO/AEO page score not found")
    return page_score


@router.get("/crawls/{crawl_id}/recommendations", response_model=GeoAeoRecommendationListResponse)
async def list_crawl_geo_aeo_recommendations(
    crawl_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    recommendation_status: Optional[GeoAeoRecommendationStatus] = Query(None, alias="status"),
    recommendation_type: Optional[GeoAeoRecommendationType] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List GEO/AEO recommendations for a crawl."""
    service = GeoAeoService(db)
    recommendations = await service.list_recommendations(
        tenant_id=current_user["tenant_id"],
        crawl_id=crawl_id,
        status=recommendation_status,
        recommendation_type=recommendation_type,
        limit=limit,
        offset=offset,
    )
    return GeoAeoRecommendationListResponse(
        recommendations=recommendations,
        limit=limit,
        offset=offset,
        has_more=len(recommendations) == limit,
    )


@router.post("/recommendations/{recommendation_id}/approve", response_model=GeoAeoRecommendationResponse)
async def approve_geo_aeo_recommendation(
    recommendation_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _set_recommendation_status(
        recommendation_id,
        current_user["tenant_id"],
        db,
        GeoAeoRecommendationStatus.approved,
    )


@router.post("/recommendations/{recommendation_id}/reject", response_model=GeoAeoRecommendationResponse)
async def reject_geo_aeo_recommendation(
    recommendation_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _set_recommendation_status(
        recommendation_id,
        current_user["tenant_id"],
        db,
        GeoAeoRecommendationStatus.rejected,
    )


@router.post("/recommendations/{recommendation_id}/mark-applied", response_model=GeoAeoRecommendationResponse)
async def mark_geo_aeo_recommendation_applied(
    recommendation_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _set_recommendation_status(
        recommendation_id,
        current_user["tenant_id"],
        db,
        GeoAeoRecommendationStatus.applied,
    )


async def _set_recommendation_status(
    recommendation_id: UUID,
    tenant_id: UUID,
    db: AsyncSession,
    recommendation_status: GeoAeoRecommendationStatus,
):
    service = GeoAeoService(db)
    try:
        return await service.update_status(recommendation_id, tenant_id, recommendation_status)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


async def run_geo_aeo_background(run_id: UUID) -> None:
    """Execute GEO/AEO analysis with a fresh DB session."""
    db = get_db_session()
    try:
        service = GeoAeoService(db)
        await service.execute_analysis(run_id)
    finally:
        await db.close()
