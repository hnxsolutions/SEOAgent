"""Manual keyword baseline routes."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.keyword_baselines import (
    KeywordBaselineBulkRequest,
    KeywordBaselineBulkResponse,
    KeywordBaselineCreate,
    KeywordBaselineListResponse,
    KeywordBaselineResponse,
    KeywordBaselineUpdate,
)
from app.services.keyword_baselines import KeywordBaselineService

router = APIRouter()


@router.post(
    "/projects/{project_id}/keyword-baselines",
    response_model=KeywordBaselineResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_keyword_baseline(
    project_id: UUID,
    payload: KeywordBaselineCreate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = KeywordBaselineService(db)
    try:
        return await service.create(project_id, _tenant_id(current_user), payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/projects/{project_id}/keyword-baselines", response_model=KeywordBaselineListResponse)
async def list_keyword_baselines(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    service = KeywordBaselineService(db)
    try:
        baselines = await service.list(project_id, _tenant_id(current_user), limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return KeywordBaselineListResponse(baselines=baselines, limit=limit, offset=offset, has_more=len(baselines) == limit)


@router.post(
    "/projects/{project_id}/keyword-baselines/bulk",
    response_model=KeywordBaselineBulkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def bulk_create_keyword_baselines(
    project_id: UUID,
    payload: KeywordBaselineBulkRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = KeywordBaselineService(db)
    try:
        baselines = await service.bulk_create(project_id, _tenant_id(current_user), payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return KeywordBaselineBulkResponse(created_count=len(baselines), baselines=baselines)


@router.put("/keyword-baselines/{baseline_id}", response_model=KeywordBaselineResponse)
async def update_keyword_baseline(
    baseline_id: UUID,
    payload: KeywordBaselineUpdate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = KeywordBaselineService(db)
    try:
        return await service.update(baseline_id, _tenant_id(current_user), payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.delete("/keyword-baselines/{baseline_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_keyword_baseline(
    baseline_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = KeywordBaselineService(db)
    try:
        await service.delete(baseline_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return None


def _tenant_id(current_user: dict) -> UUID:
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Authenticated user has no tenant context")
    return tenant_id
