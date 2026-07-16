"""SEO Brain (master orchestrator) routes — Mission Control."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.jobs.brain_jobs import run_brain_cycle_background
from app.services.seo_brain import SeoBrainService
from app.services.seo_run import SeoRunService

router = APIRouter()


def _tenant_id(current_user: dict) -> UUID:
    return current_user["tenant_id"]


@router.get("/projects/{project_id}/state")
async def brain_state(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Single Mission-Control snapshot: health, current run, pending approvals,
    per-module summaries, and the top of the master plan."""
    service = SeoBrainService(db)
    try:
        return await service.get_brain_state(project_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/projects/{project_id}/master-plan")
async def brain_master_plan(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 100,
):
    """One prioritized master plan across all modules with classification."""
    service = SeoBrainService(db)
    try:
        return await service.get_master_plan(project_id, _tenant_id(current_user), limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/projects/{project_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def brain_run_cycle(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Trigger a full brain cycle: SEO run (crawl->planner) + robots + sitemap.
    Reuses existing services; runs in the background."""
    tenant_id = _tenant_id(current_user)
    try:
        run = await SeoRunService(db).start_run(project_id, tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    background_tasks.add_task(run_brain_cycle_background, run.id, project_id, tenant_id)
    return {"status": "started", "seo_run_id": str(run.id), "project_id": str(project_id)}
