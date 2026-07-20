"""One-click SEO run API routes."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.jobs.seo_run_jobs import run_seo_run_background
from app.schemas.seo_run import SeoRunListResponse, SeoRunReportResponse, SeoRunResponse
from app.services.seo_report import SeoReportService
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
    from app.queue.client import enqueue_or_background

    enqueue_or_background(
        background_tasks, "app.queue.jobs.run_seo_run", run_seo_run_background,
        run.id, current_user["tenant_id"], max_retries=0,
    )
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


@router.get("/seo-runs/{run_id}/report", response_model=SeoRunReportResponse)
async def get_seo_run_report(
    run_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get a deterministic client-facing SEO report for one SEO run."""
    service = SeoReportService(db)
    report = await service.generate_report(run_id, current_user["tenant_id"])
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SEO run not found")
    return report


@router.get("/seo-runs/{run_id}/report.html", response_class=HTMLResponse)
async def get_seo_run_report_html(
    run_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get a print-friendly HTML SEO report for one SEO run."""
    service = SeoReportService(db)
    report = await service.generate_report(run_id, current_user["tenant_id"])
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SEO run not found")
    return HTMLResponse(service.render_html(report))
