"""Manual-assisted SERP snapshot routes."""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.serp_snapshots import (
    SerpSnapshotAssetResponse,
    SerpSnapshotCreate,
    SerpSnapshotHistoryResponse,
    SerpSnapshotListResponse,
    SerpSnapshotResponse,
    SerpSnapshotSummaryResponse,
)
from app.services.serp_snapshots import SerpSnapshotService

router = APIRouter()


@router.post("/projects/{project_id}/snapshots", response_model=SerpSnapshotResponse, status_code=status.HTTP_201_CREATED)
async def create_snapshot(
    project_id: UUID,
    payload: SerpSnapshotCreate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SerpSnapshotService(db)
    try:
        return await service.create_snapshot(project_id, _tenant_id(current_user), payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/projects/{project_id}/snapshots", response_model=SerpSnapshotListResponse)
async def list_snapshots(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    service = SerpSnapshotService(db)
    snapshots = await service.list_snapshots(project_id, _tenant_id(current_user), limit=limit, offset=offset)
    return SerpSnapshotListResponse(snapshots=snapshots, limit=limit, offset=offset, has_more=len(snapshots) == limit)


@router.get("/projects/{project_id}/history", response_model=SerpSnapshotHistoryResponse)
async def snapshot_history(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    keyword: Optional[str] = Query(None),
):
    service = SerpSnapshotService(db)
    return SerpSnapshotHistoryResponse(history=await service.history(project_id, _tenant_id(current_user), keyword=keyword))


@router.get("/projects/{project_id}/summary", response_model=SerpSnapshotSummaryResponse)
async def snapshot_summary(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SerpSnapshotService(db)
    return await service.summary(project_id, _tenant_id(current_user))


@router.get("/{snapshot_id}", response_model=SerpSnapshotResponse)
async def get_snapshot(
    snapshot_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SerpSnapshotService(db)
    snapshot = await service.get_snapshot(snapshot_id, _tenant_id(current_user))
    if not snapshot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SERP snapshot not found")
    return snapshot


@router.post("/{snapshot_id}/screenshot", response_model=SerpSnapshotAssetResponse, status_code=status.HTTP_201_CREATED)
async def upload_screenshot(
    snapshot_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
):
    service = SerpSnapshotService(db)
    try:
        return await service.add_screenshot(
            snapshot_id,
            _tenant_id(current_user),
            filename=file.filename or "serp-screenshot",
            content_type=file.content_type or "application/octet-stream",
            content=await file.read(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _tenant_id(current_user: dict) -> UUID:
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Authenticated user has no tenant context")
    return tenant_id
