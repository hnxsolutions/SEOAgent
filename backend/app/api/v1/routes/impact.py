"""SEO impact experiment routes."""
from datetime import datetime
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.impact import (
    SeoImpactExperimentCreate,
    SeoImpactExperimentListResponse,
    SeoImpactExperimentResponse,
    SeoImpactResultResponse,
    SeoImpactSnapshotResponse,
    SeoImpactSummaryResponse,
)
from app.services.impact import SeoImpactService

router = APIRouter()


@router.post("/experiments", response_model=SeoImpactExperimentResponse, status_code=status.HTTP_201_CREATED)
async def create_experiment(
    payload: SeoImpactExperimentCreate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SeoImpactService(db)
    try:
        return await service.create_experiment(_tenant_id(current_user), payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/projects/{project_id}/experiments", response_model=SeoImpactExperimentListResponse)
async def list_experiments(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    service = SeoImpactService(db)
    items = await service.list_experiments(project_id, _tenant_id(current_user), limit=limit, offset=offset)
    return SeoImpactExperimentListResponse(experiments=items, limit=limit, offset=offset, has_more=len(items) == limit)


@router.get("/experiments/{experiment_id}", response_model=SeoImpactExperimentResponse)
async def get_experiment(
    experiment_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SeoImpactService(db)
    experiment = await service.get_experiment(experiment_id, _tenant_id(current_user))
    if not experiment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SEO impact experiment not found")
    return experiment


@router.post("/experiments/{experiment_id}/capture-baseline", response_model=SeoImpactSnapshotResponse)
async def capture_baseline(
    experiment_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SeoImpactService(db)
    try:
        return await service.capture_baseline(experiment_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/experiments/{experiment_id}/mark-action-applied", response_model=SeoImpactExperimentResponse)
async def mark_action_applied(
    experiment_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    action_date: Optional[datetime] = Body(None, embed=True),
):
    service = SeoImpactService(db)
    try:
        return await service.mark_action_applied(experiment_id, _tenant_id(current_user), action_date=action_date)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/experiments/{experiment_id}/evaluate", response_model=SeoImpactResultResponse)
async def evaluate_experiment(
    experiment_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SeoImpactService(db)
    try:
        return await service.evaluate(experiment_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/projects/{project_id}/summary", response_model=SeoImpactSummaryResponse)
async def impact_summary(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SeoImpactService(db)
    return await service.summary(project_id, _tenant_id(current_user))


def _tenant_id(current_user: dict) -> UUID:
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Authenticated user has no tenant context")
    return tenant_id
