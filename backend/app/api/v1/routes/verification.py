"""After-merge verification + learning routes."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.jobs.verification_jobs import run_due_verifications_background
from app.schemas.verification import (
    LearningStatsResponse,
    SimulateMergeResponse,
    VerificationListResponse,
    VerificationResponse,
)
from app.services.learning import LearningEngine
from app.services.verification import VerificationEngine

router = APIRouter()


def _tenant_id(current_user: dict) -> UUID:
    return current_user["tenant_id"]


@router.post("/pull-requests/{pull_request_id}/simulate-merge", response_model=SimulateMergeResponse)
async def simulate_merge(
    pull_request_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    delay_minutes: int | None = None,
):
    """Mark a PR merged and enqueue verification of its applied patches. Also the
    entry point a real GitHub merge webhook would call."""
    engine = VerificationEngine(db)
    try:
        result = await engine.mark_pr_merged(pull_request_id, _tenant_id(current_user), delay_minutes=delay_minutes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return result


@router.post("/projects/{project_id}/run-due", status_code=status.HTTP_202_ACCEPTED)
async def run_due(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Manually trigger due verifications for a project (the scheduler also does
    this automatically). Runs in the background."""
    tenant_id = _tenant_id(current_user)
    background_tasks.add_task(run_due_verifications_background, tenant_id)
    return {"status": "processing", "project_id": str(project_id)}


@router.post("/{verification_id}/verify-now", response_model=VerificationResponse)
async def verify_now(
    verification_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Force a verification's before/after comparison against the latest
    completed SEO run (manual re-check / testing)."""
    engine = VerificationEngine(db)
    try:
        return await engine.verify_now(verification_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/projects/{project_id}/queue", response_model=VerificationListResponse)
async def verification_queue(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    engine = VerificationEngine(db)
    items = await engine.get_queue(project_id, _tenant_id(current_user))
    return VerificationListResponse(verifications=items, total=len(items))


@router.get("/projects/{project_id}/history", response_model=VerificationListResponse)
async def verification_history(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    engine = VerificationEngine(db)
    items = await engine.get_history(project_id, _tenant_id(current_user))
    return VerificationListResponse(verifications=items, total=len(items))


@router.get("/projects/{project_id}/learning-stats", response_model=LearningStatsResponse)
async def learning_stats(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    engine = LearningEngine(db)
    return await engine.learning_stats(_tenant_id(current_user), project_id=project_id)
