"""Scheduler / worker telemetry routes."""
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.telemetry import JobStatus
from app.services.telemetry_query import TelemetryQuery

router = APIRouter()


def _item(j) -> Dict[str, Any]:
    return {
        "id": str(j.id), "job_name": j.job_name, "job_type": j.job_type,
        "status": getattr(j.status, "value", j.status),
        "trigger_type": getattr(j.trigger_type, "value", j.trigger_type),
        "worker_name": j.worker_name, "retry_count": j.retry_count,
        "duration_ms": j.duration_ms,
        "started_at": j.started_at.isoformat() if j.started_at else None,
        "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        "error_message": j.error_message, "stack_trace": j.stack_trace,
        "project_id": str(j.project_id) if j.project_id else None,
        "seo_run_id": str(j.seo_run_id) if j.seo_run_id else None,
    }


@router.get("/stats")
async def telemetry_stats(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    window_hours: int = Query(24, ge=1, le=720),
) -> Dict[str, Any]:
    tq = TelemetryQuery(db)
    tenant_id = current_user["tenant_id"]
    return {
        "stats": await tq.stats(tenant_id, window_hours=window_hours),
        "workers": await tq.worker_health(tenant_id, window_hours=window_hours),
    }


@router.get("/job-runs")
async def job_runs(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    job_status: Optional[JobStatus] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    runs = await TelemetryQuery(db).list_runs(current_user["tenant_id"], status=job_status, limit=limit)
    return {"job_runs": [_item(j) for j in runs], "total": len(runs)}


@router.get("/failures")
async def failures(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    runs = await TelemetryQuery(db).failures(current_user["tenant_id"], limit=limit)
    return {"failures": [_item(j) for j in runs], "total": len(runs)}
