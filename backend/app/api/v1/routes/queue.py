"""Durable queue + worker monitoring routes."""
from typing import Annotated, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import get_current_user
from app.services.queue_monitor import QueueMonitor

router = APIRouter()


@router.get("/stats")
def queue_stats(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> Dict[str, Any]:
    """Queue depths, worker health/heartbeat and dead-letter counts."""
    return QueueMonitor().stats()


@router.get("/failed")
def queue_failed(
    current_user: Annotated[dict, Depends(get_current_user)],
    limit: int = Query(25, ge=1, le=100),
) -> Dict[str, Any]:
    """Dead-letter (failed) jobs with error info."""
    return {"failed": QueueMonitor().failed_jobs(limit=limit)}


@router.post("/failed/{job_id}/requeue")
def queue_requeue(
    job_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
) -> Dict[str, Any]:
    """Requeue a dead-lettered job."""
    ok = QueueMonitor().requeue_failed(job_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Failed job not found")
    return {"requeued": job_id}
