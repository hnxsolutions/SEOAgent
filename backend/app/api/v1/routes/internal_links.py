"""Internal link recommendation API routes."""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.internal_linking import (
    InternalLinkRecommendationStatus,
    InternalLinkRecommendationType,
)
from app.schemas.internal_links import (
    InternalLinkGenerationResponse,
    InternalLinkRecommendationListResponse,
    InternalLinkRecommendationResponse,
    InternalLinkSummaryResponse,
)
from app.services.internal_links import InternalLinkService

router = APIRouter()


@router.post("/crawls/{crawl_id}/generate", response_model=InternalLinkGenerationResponse)
async def generate_internal_link_recommendations(
    crawl_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(100, ge=1, le=500),
):
    """Generate deterministic internal link recommendations for a crawl."""
    service = InternalLinkService(db)
    try:
        return await service.generate_for_crawl(crawl_id, current_user["tenant_id"], limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


@router.get("/crawls/{crawl_id}/recommendations", response_model=InternalLinkRecommendationListResponse)
async def list_crawl_internal_link_recommendations(
    crawl_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    recommendation_status: Optional[InternalLinkRecommendationStatus] = Query(None, alias="status"),
    recommendation_type: Optional[InternalLinkRecommendationType] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List internal link recommendations for a crawl."""
    service = InternalLinkService(db)
    recommendations = await service.list_recommendations(
        tenant_id=current_user["tenant_id"],
        crawl_job_id=crawl_id,
        status=recommendation_status,
        recommendation_type=recommendation_type,
        limit=limit,
        offset=offset,
    )
    return InternalLinkRecommendationListResponse(
        recommendations=recommendations,
        limit=limit,
        offset=offset,
        has_more=len(recommendations) == limit,
    )


@router.get("/pages/{page_id}/recommendations", response_model=InternalLinkRecommendationListResponse)
async def list_page_internal_link_recommendations(
    page_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    recommendation_status: Optional[InternalLinkRecommendationStatus] = Query(None, alias="status"),
    recommendation_type: Optional[InternalLinkRecommendationType] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List recommendations where a page is source or target."""
    service = InternalLinkService(db)
    recommendations = await service.list_recommendations(
        tenant_id=current_user["tenant_id"],
        page_id=page_id,
        status=recommendation_status,
        recommendation_type=recommendation_type,
        limit=limit,
        offset=offset,
    )
    return InternalLinkRecommendationListResponse(
        recommendations=recommendations,
        limit=limit,
        offset=offset,
        has_more=len(recommendations) == limit,
    )


@router.post("/recommendations/{recommendation_id}/approve", response_model=InternalLinkRecommendationResponse)
async def approve_internal_link_recommendation(
    recommendation_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Approve a suggested internal link recommendation."""
    return await _set_status(recommendation_id, current_user["tenant_id"], db, InternalLinkRecommendationStatus.approved)


@router.post("/recommendations/{recommendation_id}/reject", response_model=InternalLinkRecommendationResponse)
async def reject_internal_link_recommendation(
    recommendation_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Reject an internal link recommendation."""
    return await _set_status(recommendation_id, current_user["tenant_id"], db, InternalLinkRecommendationStatus.rejected)


@router.post("/recommendations/{recommendation_id}/mark-applied", response_model=InternalLinkRecommendationResponse)
async def mark_internal_link_recommendation_applied(
    recommendation_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Mark an internal link recommendation as applied."""
    return await _set_status(recommendation_id, current_user["tenant_id"], db, InternalLinkRecommendationStatus.applied)


@router.get("/crawls/{crawl_id}/summary", response_model=InternalLinkSummaryResponse)
async def get_internal_link_summary(
    crawl_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get graph and recommendation summary for a crawl."""
    service = InternalLinkService(db)
    try:
        return await service.summary(crawl_id, current_user["tenant_id"])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


async def _set_status(
    recommendation_id: UUID,
    tenant_id: UUID,
    db: AsyncSession,
    recommendation_status: InternalLinkRecommendationStatus,
):
    service = InternalLinkService(db)
    try:
        return await service.update_status(recommendation_id, tenant_id, recommendation_status)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
