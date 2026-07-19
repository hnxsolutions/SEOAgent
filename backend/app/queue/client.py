"""Durable job queue client (RQ over the existing ``seo_queue``).

enqueue_job() puts work on the already-running RQ worker so background jobs
survive an API restart (no more fire-and-forget BackgroundTasks). It degrades
gracefully: if Redis/RQ is unavailable or the queue is disabled it returns None
so the caller can fall back to FastAPI BackgroundTasks — the system never stalls.
"""
from __future__ import annotations

from typing import Any, Optional

import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

QUEUE_NAME = "seo_queue"

# RQ job priorities via separate queues (worker listens on all).
PRIORITY_QUEUES = {"high": "seo_queue_high", "default": "seo_queue", "low": "seo_queue_low"}


def _redis_connection():
    from redis import Redis

    return Redis.from_url(settings.get_redis_url)


def get_queue(priority: str = "default"):
    """Return the RQ queue for a priority, or None if unavailable/disabled."""
    if not settings.QUEUE_ENABLED:
        return None
    try:
        from rq import Queue

        name = PRIORITY_QUEUES.get(priority, QUEUE_NAME)
        return Queue(name, connection=_redis_connection(), default_timeout=settings.QUEUE_JOB_TIMEOUT_SECONDS)
    except Exception as exc:  # pragma: no cover - infra guard
        logger.warning("queue_unavailable", error=str(exc))
        return None


def enqueue_job(
    func_path: str,
    *args: Any,
    priority: str = "default",
    max_retries: int = 2,
    job_timeout: Optional[int] = None,
    **kwargs: Any,
):
    """Enqueue ``func_path`` (a dotted import path to a top-level function) on the
    durable queue. Returns the RQ job, or None when the queue is unavailable."""
    queue = get_queue(priority)
    if queue is None:
        return None
    try:
        from rq import Retry

        job = queue.enqueue(
            func_path, *args,
            retry=Retry(max=max_retries, interval=[10, 30]) if max_retries else None,
            job_timeout=job_timeout or settings.QUEUE_JOB_TIMEOUT_SECONDS,
            **kwargs,
        )
        logger.info("job_enqueued", func=func_path, job_id=job.id, priority=priority)
        return job
    except Exception as exc:  # pragma: no cover - infra guard
        logger.warning("enqueue_failed", func=func_path, error=str(exc))
        return None


def enqueue_or_background(background_tasks, func_path: str, bg_func, *args, **enqueue_kwargs) -> str:
    """Enqueue on the durable queue; if unavailable, fall back to FastAPI
    BackgroundTasks so the work still runs. Returns the dispatch mode used."""
    job = enqueue_job(func_path, *[str(a) for a in args], **enqueue_kwargs)
    if job is not None:
        return "queued"
    if background_tasks is not None:
        background_tasks.add_task(bg_func, *args)
        return "background"
    return "skipped"
