"""Production scheduler API routes."""
import secrets
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.scheduler import (
    SchedulerTickResponse,
    SeoScheduledRunListResponse,
    SeoScheduledRunResponse,
    SeoScheduleCreate,
    SeoScheduleListResponse,
    SeoScheduleResponse,
    SeoScheduleUpdate,
)
from app.services.scheduler import SchedulerError, SchedulerService

router = APIRouter()
scheduled_runs_router = APIRouter()
internal_scheduler_router = APIRouter()


@router.post("", response_model=SeoScheduleResponse, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    payload: SeoScheduleCreate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SchedulerService(db)
    try:
        return await service.create_schedule(_tenant_id(current_user), payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/projects/{project_id}", response_model=SeoScheduleListResponse)
async def list_project_schedules(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    service = SchedulerService(db)
    schedules = await service.list_schedules(project_id, _tenant_id(current_user), limit=limit, offset=offset)
    return SeoScheduleListResponse(schedules=schedules, limit=limit, offset=offset, has_more=len(schedules) == limit)


@router.post("/tick", response_model=SchedulerTickResponse)
async def run_scheduler_tick(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Body(50, ge=1, le=200),
):
    """Run one scheduler tick for due schedules in the current tenant."""
    service = SchedulerService(db)
    result = await service.tick_with_monitor_details(tenant_id=_tenant_id(current_user), limit=limit)
    return _scheduler_tick_response(result)


@internal_scheduler_router.post("/tick", response_model=SchedulerTickResponse)
async def run_internal_scheduler_tick(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Body(50, ge=1, le=200),
    x_internal_api_key: Annotated[Optional[str], Header(alias="X-Internal-Api-Key")] = None,
):
    """Run one global scheduler tick from a trusted cron or container runner."""
    _require_internal_scheduler_key(x_internal_api_key)
    service = SchedulerService(db)
    result = await service.tick_with_monitor_details(tenant_id=None, limit=limit)
    return _scheduler_tick_response(result)


@router.get("/{schedule_id}", response_model=SeoScheduleResponse)
async def get_schedule(
    schedule_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SchedulerService(db)
    schedule = await service.get_schedule(schedule_id, _tenant_id(current_user))
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    return schedule


@router.patch("/{schedule_id}", response_model=SeoScheduleResponse)
async def update_schedule(
    schedule_id: UUID,
    payload: SeoScheduleUpdate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SchedulerService(db)
    try:
        return await service.update_schedule(schedule_id, _tenant_id(current_user), payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{schedule_id}/enable", response_model=SeoScheduleResponse)
async def enable_schedule(
    schedule_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SchedulerService(db)
    try:
        return await service.enable_schedule(schedule_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/{schedule_id}/disable", response_model=SeoScheduleResponse)
async def disable_schedule(
    schedule_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SchedulerService(db)
    try:
        return await service.disable_schedule(schedule_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/{schedule_id}/run-now", response_model=SeoScheduledRunResponse)
async def run_schedule_now(
    schedule_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SchedulerService(db)
    try:
        return await service.run_now(schedule_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except SchedulerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{schedule_id}/runs", response_model=SeoScheduledRunListResponse)
async def list_schedule_runs(
    schedule_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    service = SchedulerService(db)
    try:
        runs = await service.list_runs(schedule_id, _tenant_id(current_user), limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return SeoScheduledRunListResponse(runs=runs, limit=limit, offset=offset, has_more=len(runs) == limit)


@scheduled_runs_router.get("/{run_id}/status", response_model=SeoScheduledRunResponse)
async def get_scheduled_run_status(
    run_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SchedulerService(db)
    run = await service.get_run_status(run_id, _tenant_id(current_user))
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduled run not found")
    return run


def _tenant_id(current_user: dict) -> UUID:
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Authenticated user has no tenant context")
    return tenant_id


def _require_internal_scheduler_key(value: Optional[str]) -> None:
    configured = settings.SCHEDULER_INTERNAL_API_KEY
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SCHEDULER_INTERNAL_API_KEY is not configured.",
        )
    if not value or not secrets.compare_digest(value, configured):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid scheduler internal API key.")


def _scheduler_tick_response(result: dict) -> SchedulerTickResponse:
    return SchedulerTickResponse(
        due_count=int(result.get("due_count") or 0),
        runs_created=int(result.get("runs_created") or 0),
        runs=list(result.get("runs") or []),
        gsc_monitor_due_count=int(result.get("gsc_monitor_due_count") or 0),
        gsc_monitor_jobs_created=int(result.get("gsc_monitor_jobs_created") or 0),
        gsc_monitor_jobs=list(result.get("gsc_monitor_jobs") or []),
    )
