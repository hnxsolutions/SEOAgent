"""Auto Index Queue routes (official sitemap-based submission only)."""
from datetime import datetime
from typing import Annotated, Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.index_queue import IndexUrlSource, IndexUrlStatus
from app.services.index_queue import IndexQueueService

router = APIRouter()


def _tenant_id(u: dict) -> UUID:
    return u["tenant_id"]


class PendingIndexUrlResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    project_id: UUID
    url: str
    source: IndexUrlSource
    status: IndexUrlStatus
    eligible: bool
    reason: Optional[str] = None
    submitted_via: Optional[str] = None
    discovered_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None


class ScheduleRequest(BaseModel):
    scheduled_at: Optional[datetime] = None


@router.post("/projects/{project_id}/discover")
async def discover_urls(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Dict[str, Any]:
    """Discover indexable URLs from the latest crawl + blog drafts into the queue."""
    try:
        return await IndexQueueService(db).discover(project_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/projects/{project_id}/queue")
async def list_queue(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    url_status: Optional[IndexUrlStatus] = Query(None, alias="status"),
    limit: int = Query(500, ge=1, le=1000),
):
    items = await IndexQueueService(db).list_queue(project_id, _tenant_id(current_user), status=url_status, limit=limit)
    return {"items": [PendingIndexUrlResponse.model_validate(i) for i in items], "total": len(items)}


@router.get("/projects/{project_id}/summary")
async def queue_summary(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Dict[str, Any]:
    return await IndexQueueService(db).summary(project_id, _tenant_id(current_user))


@router.post("/{url_id}/approve", response_model=PendingIndexUrlResponse)
async def approve_url(url_id: UUID, current_user: Annotated[dict, Depends(get_current_user)],
                      db: Annotated[AsyncSession, Depends(get_db)]):
    row = await IndexQueueService(db).set_status(url_id, _tenant_id(current_user), IndexUrlStatus.approved)
    if not row:
        raise HTTPException(status_code=404, detail="URL not found")
    return row


@router.post("/{url_id}/reject", response_model=PendingIndexUrlResponse)
async def reject_url(url_id: UUID, current_user: Annotated[dict, Depends(get_current_user)],
                     db: Annotated[AsyncSession, Depends(get_db)]):
    row = await IndexQueueService(db).set_status(url_id, _tenant_id(current_user), IndexUrlStatus.rejected)
    if not row:
        raise HTTPException(status_code=404, detail="URL not found")
    return row


@router.post("/{url_id}/schedule", response_model=PendingIndexUrlResponse)
async def schedule_url(url_id: UUID, payload: ScheduleRequest,
                       current_user: Annotated[dict, Depends(get_current_user)],
                       db: Annotated[AsyncSession, Depends(get_db)]):
    row = await IndexQueueService(db).set_status(url_id, _tenant_id(current_user), IndexUrlStatus.scheduled,
                                                 scheduled_at=payload.scheduled_at)
    if not row:
        raise HTTPException(status_code=404, detail="URL not found")
    return row


@router.post("/projects/{project_id}/approve-all")
async def approve_all(project_id: UUID, current_user: Annotated[dict, Depends(get_current_user)],
                      db: Annotated[AsyncSession, Depends(get_db)]) -> Dict[str, Any]:
    n = await IndexQueueService(db).approve_all(project_id, _tenant_id(current_user))
    return {"approved": n}


@router.post("/projects/{project_id}/submit")
async def submit_approved(project_id: UUID, current_user: Annotated[dict, Depends(get_current_user)],
                          db: Annotated[AsyncSession, Depends(get_db)]) -> Dict[str, Any]:
    """Submit approved URLs via official sitemap (re)submission. Credential-gated:
    degrades gracefully when Search Console is not connected. Never uses a per-URL
    indexing API (Google does not offer one for general pages)."""
    return await IndexQueueService(db).submit_approved(project_id, _tenant_id(current_user))
