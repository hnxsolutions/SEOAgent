"""Enterprise Mission Control overview + real-time SSE stream."""
import asyncio
import json
from datetime import datetime
from typing import Annotated, Any, Dict

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, get_db_session
from app.core.security import get_current_user
from app.models.pipeline import PipelineStageRun
from app.models.telemetry import SchedulerJobRun
from app.services.mission_control import MissionControlService

router = APIRouter()


@router.get("/overview")
async def mission_control_overview(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Dict[str, Any]:
    """One tenant-wide snapshot of the whole AI SEO system for the dashboard."""
    return await MissionControlService(db).overview(current_user["tenant_id"])


@router.get("/stream")
async def mission_control_stream(
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Server-Sent Events stream of REAL backend job/stage telemetry deltas.

    The browser holds one connection (no polling); the server emits an event
    whenever a job or pipeline stage is created/updated. Events are read from the
    telemetry tables — never synthesized. Uses short-lived sessions per poll so
    no DB connection is held open.
    """
    tenant_id = current_user["tenant_id"]

    async def event_stream():
        yield f"event: hello\ndata: {json.dumps({'connected': True, 'ts': datetime.utcnow().isoformat()})}\n\n"
        cursor = datetime.utcnow()
        ticks = 0
        while True:
            emitted = False
            db = get_db_session()
            try:
                jobs = (await db.execute(
                    select(SchedulerJobRun).where(
                        or_(SchedulerJobRun.tenant_id == tenant_id, SchedulerJobRun.tenant_id.is_(None)),
                        SchedulerJobRun.updated_at > cursor,
                    ).order_by(SchedulerJobRun.updated_at.asc()).limit(50)
                )).scalars().all()
                stages = (await db.execute(
                    select(PipelineStageRun).where(
                        PipelineStageRun.tenant_id == tenant_id,
                        PipelineStageRun.updated_at > cursor,
                    ).order_by(PipelineStageRun.updated_at.asc()).limit(50)
                )).scalars().all()
            finally:
                await db.close()

            newest = cursor
            for j in jobs:
                emitted = True
                newest = max(newest, j.updated_at or newest)
                yield "event: job\ndata: " + json.dumps({
                    "id": str(j.id), "job_name": j.job_name, "status": _v(j.status),
                    "duration_ms": j.duration_ms, "retry_count": j.retry_count,
                    "worker_name": j.worker_name,
                }) + "\n\n"
            for s in stages:
                emitted = True
                newest = max(newest, s.updated_at or newest)
                yield "event: stage\ndata: " + json.dumps({
                    "id": str(s.id), "stage": s.stage_name, "status": _v(s.status),
                    "duration_ms": s.duration_ms, "seo_run_id": str(s.seo_run_id) if s.seo_run_id else None,
                    "project_id": str(s.project_id) if s.project_id else None,
                }) + "\n\n"
            cursor = newest

            if not emitted:
                yield ": heartbeat\n\n"  # SSE comment keeps the connection alive
            ticks += 1
            if ticks >= 150:  # ~5 min; the browser transparently reconnects
                yield "event: bye\ndata: {}\n\n"
                break
            await asyncio.sleep(2)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _v(value):
    return getattr(value, "value", value)
