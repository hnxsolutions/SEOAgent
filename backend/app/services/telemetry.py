"""Job telemetry + retry engine.

`run_with_telemetry` wraps any background job body: it writes one
SchedulerJobRun row (running -> completed/failed), times it, captures the error
and stack on failure, and retries transient failures (timeout / network / Ollama
/ GitHub / Google unavailable) while never retrying deterministic ones
(validation / configuration / permission). Telemetry uses its own DB session so
it is recorded even if the job's own transaction rolls back.
"""
from __future__ import annotations

import asyncio
import time
import traceback
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional
from uuid import UUID, uuid4

import structlog

from app.core.database import get_db_session
from app.models.telemetry import JobStatus, JobTriggerType, SchedulerJobRun

logger = structlog.get_logger(__name__)

WORKER_NAME = "seo-agent-worker"

# Substrings that mark a transient, retryable failure.
_RETRYABLE_MARKERS = (
    "timeout", "timed out", "temporarily unavailable", "connection", "connlost",
    "connection reset", "connection refused", "network", "not reachable",
    "ollama", "rate limit", "429", "502", "503", "504", "unavailable",
    "econnreset", "dns", "getaddrinfo",
)
# Substrings that mark a deterministic failure that must NOT be retried.
_NON_RETRYABLE_MARKERS = (
    "validation", "invalid", "permission", "forbidden", "unauthorized", "401",
    "403", "not found", "404", "missing configuration", "missing config",
    "no such", "does not exist", "value too long", "integrity",
)


def is_retryable(exc: BaseException) -> bool:
    """Classify an exception as transient (retryable) or deterministic."""
    text = f"{type(exc).__name__}: {exc}".lower()
    if any(m in text for m in _NON_RETRYABLE_MARKERS):
        return False
    # asyncio/httpx timeouts by type
    if isinstance(exc, (asyncio.TimeoutError,)):
        return True
    return any(m in text for m in _RETRYABLE_MARKERS)


async def _write(job_id: UUID, **fields: Any) -> None:
    """Update a telemetry row in an independent session (best-effort)."""
    db = get_db_session()
    try:
        run = await db.get(SchedulerJobRun, job_id)
        if not run:
            return
        for key, value in fields.items():
            setattr(run, key, value)
        await db.commit()
    except Exception:  # pragma: no cover - telemetry must never break a job
        logger.warning("telemetry_write_failed", job_id=str(job_id))
    finally:
        await db.close()


async def _create(job_name: str, job_type: str, trigger_type: JobTriggerType,
                  tenant_id: Optional[UUID], project_id: Optional[UUID]) -> UUID:
    job_id = uuid4()
    db = get_db_session()
    try:
        db.add(SchedulerJobRun(
            id=job_id, tenant_id=tenant_id, project_id=project_id,
            job_name=job_name, job_type=job_type, trigger_type=trigger_type,
            worker_name=WORKER_NAME, status=JobStatus.running,
            retry_count=0, started_at=datetime.utcnow(), previous_run=await _previous_run(db, job_name),
        ))
        await db.commit()
    except Exception:  # pragma: no cover
        logger.warning("telemetry_create_failed", job_name=job_name)
    finally:
        await db.close()
    return job_id


async def _previous_run(db, job_name: str):
    from sqlalchemy import select

    row = (await db.execute(
        select(SchedulerJobRun.started_at).where(
            SchedulerJobRun.job_name == job_name,
            SchedulerJobRun.status == JobStatus.completed,
        ).order_by(SchedulerJobRun.started_at.desc()).limit(1)
    )).scalars().first()
    return row


async def run_with_telemetry(
    job_name: str,
    job_type: str,
    func: Callable[[], Awaitable[Any]],
    *,
    trigger_type: JobTriggerType = JobTriggerType.automatic,
    tenant_id: Optional[UUID] = None,
    project_id: Optional[UUID] = None,
    max_retries: int = 2,
    base_delay: float = 1.0,
    reraise: bool = False,
) -> Any:
    """Run ``func`` with one telemetry row + transient-failure retries."""
    job_id = await _create(job_name, job_type, trigger_type, tenant_id, project_id)
    started = time.monotonic()
    attempt = 0
    while True:
        try:
            result = await func()
            await _write(
                job_id, status=JobStatus.completed, finished_at=datetime.utcnow(),
                duration_ms=int((time.monotonic() - started) * 1000), retry_count=attempt,
            )
            return result
        except Exception as exc:  # noqa: BLE001 - telemetry classifies + records
            retryable = is_retryable(exc)
            if retryable and attempt < max_retries:
                attempt += 1
                await _write(
                    job_id, status=JobStatus.retrying, retry_count=attempt,
                    error_message=f"retry {attempt}: {exc}"[:2000],
                )
                logger.warning("job_retry", job_name=job_name, attempt=attempt, error=str(exc))
                await asyncio.sleep(base_delay * (2 ** (attempt - 1)))
                continue
            await _write(
                job_id, status=JobStatus.failed, finished_at=datetime.utcnow(),
                duration_ms=int((time.monotonic() - started) * 1000), retry_count=attempt,
                error_message=str(exc)[:2000], stack_trace=traceback.format_exc()[:8000],
            )
            logger.error("job_failed", job_name=job_name, retryable=retryable, error=str(exc))
            if reraise:
                raise
            return None
