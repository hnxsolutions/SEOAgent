"""One-click SEO run API routes."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, get_db_session
from app.core.security import get_current_user
from app.schemas.seo_run import SeoRunListResponse, SeoRunResponse
from app.services.seo_run import SeoRunService

router = APIRouter()


@router.post(
    "/projects/{project_id}/seo-run",
    response_model=SeoRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_project_seo_run(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Start a one-click SEO run for a project."""
    service = SeoRunService(db)
    try:
        run = await service.start_run(project_id, current_user["tenant_id"])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    background_tasks.add_task(run_seo_run_background, run.id, current_user["tenant_id"])
    return run


@router.get("/projects/{project_id}/seo-runs", response_model=SeoRunListResponse)
async def list_project_seo_runs(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List one-click SEO runs for a project."""
    service = SeoRunService(db)
    runs = await service.list_runs(project_id, current_user["tenant_id"], limit=limit, offset=offset)
    return SeoRunListResponse(runs=runs, limit=limit, offset=offset, has_more=len(runs) == limit)


@router.get("/seo-runs/{run_id}/status", response_model=SeoRunResponse)
async def get_seo_run_status(
    run_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get one-click SEO run status."""
    service = SeoRunService(db)
    run = await service.get_run_status(run_id, current_user["tenant_id"])
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SEO run not found")
    return run


async def run_seo_run_background(run_id: UUID, tenant_id: UUID) -> None:
    """Execute one-click SEO run with a fresh DB session."""
    db = get_db_session()
    try:
        service = SeoRunService(db)
        await service.execute_run(run_id, tenant_id)
    finally:
        await db.close()
