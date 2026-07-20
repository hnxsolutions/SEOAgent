"""Queue + worker monitoring over RQ (queues, workers, heartbeat, dead-letter).

Read-only introspection of the durable RQ queue for Mission Control and the
queue API. Degrades gracefully to a disabled/unavailable status when Redis or RQ
is not reachable.
"""
from __future__ import annotations

from typing import Any, Dict, List

import structlog

from app.core.config import settings
from app.queue.client import PRIORITY_QUEUES, _redis_connection

logger = structlog.get_logger(__name__)


class QueueMonitor:
    def stats(self) -> Dict[str, Any]:
        if not settings.QUEUE_ENABLED:
            return {"status": "disabled", "queues": [], "workers": [], "dead_letter": 0}
        try:
            from rq import Queue, Worker
            from rq.registry import FailedJobRegistry, StartedJobRegistry

            conn = _redis_connection()
            queues = []
            total_pending = total_started = total_failed = total_finished = 0
            for label, name in PRIORITY_QUEUES.items():
                q = Queue(name, connection=conn)
                pending = len(q)
                started = len(StartedJobRegistry(name, connection=conn))
                failed = len(FailedJobRegistry(name, connection=conn))
                finished = len(q.finished_job_registry)
                total_pending += pending
                total_started += started
                total_failed += failed
                total_finished += finished
                queues.append({
                    "name": name, "priority": label,
                    "pending": pending, "running": started, "failed": failed, "finished": finished,
                })

            workers = []
            for w in Worker.all(connection=conn):
                hb = w.last_heartbeat
                workers.append({
                    "name": w.name,
                    "state": w.get_state(),
                    "current_job": w.get_current_job_id(),
                    "successful_jobs": w.successful_job_count,
                    "failed_jobs": w.failed_job_count,
                    "last_heartbeat": hb.isoformat() if hb else None,
                    "queues": [qq.name for qq in w.queues],
                })

            return {
                "status": "available",
                "totals": {
                    "pending": total_pending, "running": total_started,
                    "failed": total_failed, "finished": total_finished,
                },
                "queues": queues,
                "workers": workers,
                "worker_count": len(workers),
                "dead_letter": total_failed,
            }
        except Exception as exc:  # pragma: no cover - infra guard
            logger.warning("queue_stats_unavailable", error=str(exc))
            return {"status": "unavailable", "error": str(exc), "queues": [], "workers": [], "dead_letter": 0}

    def failed_jobs(self, limit: int = 25) -> List[Dict[str, Any]]:
        if not settings.QUEUE_ENABLED:
            return []
        try:
            from rq import Queue
            from rq.job import Job
            from rq.registry import FailedJobRegistry

            conn = _redis_connection()
            out: List[Dict[str, Any]] = []
            for label, name in PRIORITY_QUEUES.items():
                reg = FailedJobRegistry(name, connection=conn)
                for job_id in reg.get_job_ids()[:limit]:
                    try:
                        job = Job.fetch(job_id, connection=conn)
                        out.append({
                            "id": job.id, "queue": name, "func": job.func_name,
                            "enqueued_at": job.enqueued_at.isoformat() if job.enqueued_at else None,
                            "error": (job.exc_info or "")[-500:] if job.exc_info else None,
                            "retries_left": job.retries_left,
                        })
                    except Exception:
                        continue
            return out[:limit]
        except Exception as exc:  # pragma: no cover
            logger.warning("failed_jobs_unavailable", error=str(exc))
            return []

    def requeue_failed(self, job_id: str) -> bool:
        if not settings.QUEUE_ENABLED:
            return False
        try:
            from rq import Queue
            from rq.registry import FailedJobRegistry

            conn = _redis_connection()
            for label, name in PRIORITY_QUEUES.items():
                reg = FailedJobRegistry(name, connection=conn)
                if job_id in reg.get_job_ids():
                    reg.requeue(job_id)
                    return True
            return False
        except Exception as exc:  # pragma: no cover
            logger.warning("requeue_failed_error", error=str(exc))
            return False
