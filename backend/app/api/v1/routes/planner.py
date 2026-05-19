"""Weekly autonomous SEO planner routes."""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.planner import SeoTaskStatus
from app.schemas.planner import (
    PlannerProjectSummaryResponse,
    PlannerRunRequest,
    SeoPlannerRunListResponse,
    SeoPlannerRunResponse,
    SeoTaskListResponse,
    SeoTaskResponse,
    SeoWeeklyReportResponse,
)
from app.services.planner import PlannerError, PlannerService

router = APIRouter()


@router.post("/projects/{project_id}/run", response_model=SeoPlannerRunResponse)
async def run_project_planner(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: PlannerRunRequest = Body(default_factory=PlannerRunRequest),
):
    """Run the weekly SEO planner now for a project."""
    service = PlannerService(db)
    try:
        return await service.run_project(
            project_id,
            _tenant_id(current_user),
            run_type=payload.run_type,
            target_week_start=payload.target_week_start,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PlannerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/runs/{run_id}/status", response_model=SeoPlannerRunResponse)
async def get_planner_run_status(
    run_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = PlannerService(db)
    run = await service.get_run_status(run_id, _tenant_id(current_user))
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planner run not found")
    return run


@router.get("/projects/{project_id}/runs", response_model=SeoPlannerRunListResponse)
async def list_project_planner_runs(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    service = PlannerService(db)
    runs = await service.list_runs(project_id, _tenant_id(current_user), limit=limit, offset=offset)
    return SeoPlannerRunListResponse(runs=runs, limit=limit, offset=offset, has_more=len(runs) == limit)


@router.get("/projects/{project_id}/tasks", response_model=SeoTaskListResponse)
async def list_project_planner_tasks(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    task_status: Optional[SeoTaskStatus] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    service = PlannerService(db)
    tasks = await service.list_tasks(
        project_id,
        _tenant_id(current_user),
        status=task_status,
        limit=limit,
        offset=offset,
    )
    return SeoTaskListResponse(tasks=tasks, limit=limit, offset=offset, has_more=len(tasks) == limit)


@router.get("/tasks/{task_id}", response_model=SeoTaskResponse)
async def get_planner_task(
    task_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = PlannerService(db)
    task = await service.get_task(task_id, _tenant_id(current_user))
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SEO task not found")
    return task


@router.post("/tasks/{task_id}/approve", response_model=SeoTaskResponse)
async def approve_planner_task(
    task_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _set_task_status(task_id, current_user, db, SeoTaskStatus.approved)


@router.post("/tasks/{task_id}/reject", response_model=SeoTaskResponse)
async def reject_planner_task(
    task_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _set_task_status(task_id, current_user, db, SeoTaskStatus.rejected)


@router.post("/tasks/{task_id}/mark-in-progress", response_model=SeoTaskResponse)
async def mark_planner_task_in_progress(
    task_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _set_task_status(task_id, current_user, db, SeoTaskStatus.in_progress)


@router.post("/tasks/{task_id}/mark-completed", response_model=SeoTaskResponse)
async def mark_planner_task_completed(
    task_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _set_task_status(task_id, current_user, db, SeoTaskStatus.completed)


@router.get("/runs/{run_id}/report", response_model=SeoWeeklyReportResponse)
async def get_planner_report(
    run_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = PlannerService(db)
    report = await service.get_report(run_id, _tenant_id(current_user))
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Weekly report not found")
    return report


@router.get("/projects/{project_id}/summary", response_model=PlannerProjectSummaryResponse)
async def get_project_planner_summary(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = PlannerService(db)
    return await service.project_summary(project_id, _tenant_id(current_user))


async def _set_task_status(task_id: UUID, current_user: dict, db: AsyncSession, task_status: SeoTaskStatus):
    service = PlannerService(db)
    try:
        return await service.update_task_status(task_id, _tenant_id(current_user), task_status)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _tenant_id(current_user: dict) -> UUID:
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Authenticated user has no tenant context")
    return tenant_id
