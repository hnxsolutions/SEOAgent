"""Read-side telemetry: job-run stats, failures and worker health for Mission
Control and the telemetry API. Pure aggregation over scheduler_job_runs."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import Integer, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telemetry import JobStatus, SchedulerJobRun

_ACTIVE = (JobStatus.running, JobStatus.retrying, JobStatus.queued)
_TERMINAL = (JobStatus.completed, JobStatus.failed, JobStatus.cancelled)


class TelemetryQuery:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _scope(self, query, tenant_id: Optional[UUID]):
        # System jobs (tenant_id NULL) are visible to every tenant's dashboard.
        if tenant_id is not None:
            return query.where(or_(SchedulerJobRun.tenant_id == tenant_id, SchedulerJobRun.tenant_id.is_(None)))
        return query

    async def stats(self, tenant_id: Optional[UUID], window_hours: int = 24) -> Dict[str, Any]:
        since = datetime.utcnow() - timedelta(hours=window_hours)
        rows = (await self.db.execute(self._scope(
            select(SchedulerJobRun.status, func.count(SchedulerJobRun.id))
            .where(SchedulerJobRun.created_at >= since), tenant_id
        ).group_by(SchedulerJobRun.status))).all()
        by_status = {self._enum(s): int(c) for s, c in rows}

        completed = by_status.get("completed", 0)
        failed = by_status.get("failed", 0)
        finalized = completed + failed + by_status.get("cancelled", 0)
        running = by_status.get("running", 0)
        retrying = by_status.get("retrying", 0)

        retried = int((await self.db.execute(self._scope(
            select(func.count(SchedulerJobRun.id)).where(
                SchedulerJobRun.created_at >= since, SchedulerJobRun.retry_count > 0), tenant_id
        ))).scalar() or 0)
        total = sum(by_status.values())

        avg_ms = (await self.db.execute(self._scope(
            select(func.avg(SchedulerJobRun.duration_ms)).where(
                SchedulerJobRun.created_at >= since, SchedulerJobRun.status == JobStatus.completed), tenant_id
        ))).scalar()
        longest = (await self.db.execute(self._scope(
            select(SchedulerJobRun).where(
                SchedulerJobRun.created_at >= since, SchedulerJobRun.duration_ms.isnot(None)), tenant_id
        ).order_by(SchedulerJobRun.duration_ms.desc()).limit(1))).scalars().first()

        return {
            "window_hours": window_hours,
            "total": total,
            "by_status": by_status,
            "running": running,
            "retrying": retrying,
            "success_rate": round(completed / finalized * 100, 1) if finalized else None,
            "failure_rate": round(failed / finalized * 100, 1) if finalized else None,
            "retry_rate": round(retried / total * 100, 1) if total else None,
            "average_duration_ms": int(avg_ms) if avg_ms is not None else None,
            "longest_job": {
                "job_name": longest.job_name, "duration_ms": longest.duration_ms,
                "status": self._enum(longest.status),
            } if longest else None,
        }

    async def worker_health(self, tenant_id: Optional[UUID], window_hours: int = 24) -> List[Dict[str, Any]]:
        since = datetime.utcnow() - timedelta(hours=window_hours)
        rows = (await self.db.execute(self._scope(
            select(
                SchedulerJobRun.job_name,
                func.count(SchedulerJobRun.id),
                func.avg(SchedulerJobRun.duration_ms),
                func.sum(case((SchedulerJobRun.status == JobStatus.failed, 1), else_=0)),
            ).where(SchedulerJobRun.created_at >= since), tenant_id
        ).group_by(SchedulerJobRun.job_name))).all()
        out = []
        for name, count, avg_ms, failed in rows:
            out.append({
                "job_name": name,
                "runs": int(count),
                "avg_duration_ms": int(avg_ms) if avg_ms is not None else None,
                "failed": int(failed or 0),
            })
        out.sort(key=lambda w: w["runs"], reverse=True)
        return out

    async def list_runs(self, tenant_id: Optional[UUID], status: Optional[JobStatus] = None,
                        limit: int = 50) -> List[SchedulerJobRun]:
        query = self._scope(select(SchedulerJobRun), tenant_id)
        if status:
            query = query.where(SchedulerJobRun.status == status)
        rows = await self.db.execute(query.order_by(SchedulerJobRun.created_at.desc()).limit(limit))
        return list(rows.scalars().all())

    #: How far back the Failure Center looks.
    #:
    #: Without a window it showed every failure ever recorded, so a one-off from
    #: July sat at the top of the list months later, indistinguishable from
    #: something broken this morning. An operator reading it could not tell what
    #: needed attention — which is the only thing the panel is for. Failures
    #: older than this are history, and history belongs in the run list.
    FAILURE_WINDOW_HOURS = 24

    async def failures(
        self,
        tenant_id: Optional[UUID],
        limit: int = 20,
        within_hours: Optional[int] = None,
    ) -> List[SchedulerJobRun]:
        """Recent failures only. Pass `within_hours=None` deliberately for all of them."""
        window = self.FAILURE_WINDOW_HOURS if within_hours is None else within_hours
        cutoff = datetime.utcnow() - timedelta(hours=window)
        rows = await self.db.execute(
            self._scope(
                select(SchedulerJobRun).where(
                    SchedulerJobRun.status == JobStatus.failed,
                    SchedulerJobRun.started_at >= cutoff,
                ),
                tenant_id,
            )
            .order_by(SchedulerJobRun.started_at.desc())
            .limit(limit)
        )
        return list(rows.scalars().all())

    async def active_runs(self, tenant_id: Optional[UUID]) -> List[SchedulerJobRun]:
        rows = await self.db.execute(self._scope(
            select(SchedulerJobRun).where(SchedulerJobRun.status.in_(_ACTIVE)), tenant_id
        ).order_by(SchedulerJobRun.started_at.desc()).limit(50))
        return list(rows.scalars().all())

    @staticmethod
    def _enum(value):
        return getattr(value, "value", value)
