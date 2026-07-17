"""Per-stage pipeline telemetry recorder + analytics.

record_stage() upserts one PipelineStageRun per (seo_run, stage) as the SEO run
progresses, driven from SeoRunService._set_stage (the existing per-stage hook) —
no stage logic is duplicated. StageTelemetryQuery aggregates per-stage analytics
and the latest run's pipeline for Mission Control's visualisation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import PipelineStageRun
from app.models.seo_run import SeoRun, SeoRunStatus
from app.models.telemetry import JobStatus

logger = structlog.get_logger(__name__)

# Ordered pipeline stages for the visualisation.
PIPELINE_STAGES = ["crawl", "audit", "semantic_index", "content_optimization", "planner"]

_STATUS_MAP = {
    "pending": JobStatus.queued,
    "queued": JobStatus.queued,
    "running": JobStatus.running,
    "completed": JobStatus.completed,
    "failed": JobStatus.failed,
    "retrying": JobStatus.retrying,
    "cancelled": JobStatus.cancelled,
}


def _coerce(status) -> JobStatus:
    value = getattr(status, "value", status)
    return _STATUS_MAP.get(str(value), JobStatus.running)


async def record_stage(db: AsyncSession, run, stage, status, error_message: Optional[str] = None) -> None:
    """Upsert a per-stage telemetry row (best-effort; never breaks the run)."""
    stage_name = str(getattr(stage, "value", stage))
    job_status = _coerce(status)
    try:
        existing = (await db.execute(
            select(PipelineStageRun).where(
                PipelineStageRun.seo_run_id == run.id,
                PipelineStageRun.stage_name == stage_name,
            )
        )).scalars().first()
        now = datetime.utcnow()
        if not existing:
            existing = PipelineStageRun(
                tenant_id=getattr(run, "tenant_id", None),
                project_id=getattr(run, "project_id", None),
                seo_run_id=run.id,
                stage_name=stage_name,
                worker_name="seo-agent-worker",
                status=job_status,
                started_at=now if job_status == JobStatus.running else None,
            )
            db.add(existing)
        else:
            if job_status == JobStatus.running and not existing.started_at:
                existing.started_at = now
            existing.status = job_status
        if job_status in (JobStatus.completed, JobStatus.failed, JobStatus.cancelled):
            existing.finished_at = now
            if existing.started_at:
                existing.duration_ms = int((now - existing.started_at).total_seconds() * 1000)
        if error_message:
            existing.error_message = error_message[:2000]
        await db.commit()
    except Exception:  # pragma: no cover - telemetry must never break a run
        logger.warning("stage_telemetry_failed", stage=stage_name)
        try:
            await db.rollback()
        except Exception:
            pass


class StageTelemetryQuery:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def latest_pipeline(self, tenant_id: UUID, project_id: Optional[UUID] = None) -> Dict[str, Any]:
        """The most recent run's stages in pipeline order, for the visualisation.

        Prefers a specific project's latest run when given (e.g. an actively
        running one); otherwise shows the most recent run across the tenant so
        the panel keeps showing the last pipeline after it finishes.
        """
        query = select(SeoRun).where(SeoRun.tenant_id == tenant_id)
        if project_id is not None:
            query = query.where(SeoRun.project_id == project_id)
        run = (await self.db.execute(
            query.order_by(SeoRun.created_at.desc()).limit(1)
        )).scalars().first()
        if not run:
            return {"run_id": None, "run_status": None, "stages": []}
        rows = (await self.db.execute(
            select(PipelineStageRun).where(PipelineStageRun.seo_run_id == run.id)
        )).scalars().all()
        by_stage = {r.stage_name: r for r in rows}
        stages = []
        for name in PIPELINE_STAGES:
            r = by_stage.get(name)
            stages.append({
                "stage": name,
                "status": self._enum(r.status) if r else "waiting",
                "duration_ms": r.duration_ms if r else None,
                "started_at": r.started_at.isoformat() if r and r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r and r.finished_at else None,
                "retry_count": r.retry_count if r else 0,
                "error_message": r.error_message if r else None,
            })
        return {
            "run_id": str(run.id),
            "run_status": self._enum(run.status),
            "current_stage": self._enum(getattr(run, "current_stage", None)),
            "stages": stages,
        }

    async def stage_analytics(self, tenant_id: Optional[UUID], limit_runs: int = 200) -> Dict[str, Any]:
        """Per-stage averages + success/failure/retry rates across recent runs."""
        rows = (await self.db.execute(
            select(
                PipelineStageRun.stage_name,
                func.count(PipelineStageRun.id),
                func.avg(PipelineStageRun.duration_ms),
                func.sum(case((PipelineStageRun.status == JobStatus.completed, 1), else_=0)),
                func.sum(case((PipelineStageRun.status == JobStatus.failed, 1), else_=0)),
            ).group_by(PipelineStageRun.stage_name)
        )).all()
        stages = []
        for name, count, avg_ms, completed, failed in rows:
            total = int(count)
            stages.append({
                "stage": name,
                "runs": total,
                "avg_duration_ms": int(avg_ms) if avg_ms is not None else None,
                "success_rate": round(int(completed or 0) / total * 100, 1) if total else None,
                "failure_rate": round(int(failed or 0) / total * 100, 1) if total else None,
            })
        stages.sort(key=lambda s: PIPELINE_STAGES.index(s["stage"]) if s["stage"] in PIPELINE_STAGES else 99)
        timed = [s for s in stages if s["avg_duration_ms"] is not None]
        fastest = min(timed, key=lambda s: s["avg_duration_ms"]) if timed else None
        slowest = max(timed, key=lambda s: s["avg_duration_ms"]) if timed else None
        return {
            "stages": stages,
            "fastest_stage": fastest["stage"] if fastest else None,
            "slowest_stage": slowest["stage"] if slowest else None,
        }

    @staticmethod
    def _enum(value):
        return getattr(value, "value", value)
