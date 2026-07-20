"""Code Review (human approval) routes.

The AI prepares reviews and waits. An admin lists them, opens per-file diffs with
explanations + predicted impact + risk, and explicitly Approves / Rejects /
Archives. Approve is the ONLY path that merges the PR — nothing merges
automatically.
"""
from typing import Annotated, Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.services.code_review import CodeReviewService

router = APIRouter()


def _tenant_id(u: dict) -> UUID:
    return u["tenant_id"]


def _admin(u: dict) -> str:
    return u.get("email") or u.get("username") or str(u.get("sub") or "admin")


class RejectRequest(BaseModel):
    reason: str


@router.post("/projects/{project_id}/prepare")
async def prepare_review(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Dict[str, Any]:
    try:
        return await CodeReviewService(db).prepare(project_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("")
async def list_reviews(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    review_status: Optional[str] = Query(None, alias="status"),
    project_id: Optional[UUID] = None,
):
    items = await CodeReviewService(db).list_reviews(_tenant_id(current_user), status=review_status, project_id=project_id)
    svc = CodeReviewService(db)
    return {"items": [svc._shape(i) for i in items], "total": len(items)}


@router.get("/summary")
async def review_summary(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Dict[str, Any]:
    return await CodeReviewService(db).mission_control_summary(_tenant_id(current_user))


@router.get("/{review_id}")
async def get_review(
    review_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Dict[str, Any]:
    detail = await CodeReviewService(db).detail(review_id, _tenant_id(current_user))
    if not detail:
        raise HTTPException(status_code=404, detail="Review not found")
    return detail


@router.post("/{review_id}/approve")
async def approve_review(
    review_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Dict[str, Any]:
    try:
        return await CodeReviewService(db).approve(review_id, _tenant_id(current_user), _admin(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/{review_id}/reject")
async def reject_review(
    review_id: UUID,
    payload: RejectRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Dict[str, Any]:
    try:
        return await CodeReviewService(db).reject(review_id, _tenant_id(current_user), _admin(current_user), payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/{review_id}/archive")
async def archive_review(
    review_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Dict[str, Any]:
    try:
        return await CodeReviewService(db).archive(review_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
