"""Synchronous RQ entrypoints that run the existing async background jobs.

RQ workers are synchronous, so each entrypoint drives the existing async job
coroutine with asyncio.run — the job logic itself is reused unchanged. A failure
here is re-raised so RQ records it in the FailedJobRegistry (the dead-letter
queue) and applies the configured retry policy.
"""
import asyncio
from uuid import UUID

import structlog

logger = structlog.get_logger(__name__)


def _uuid(v):
    return v if isinstance(v, UUID) else UUID(str(v))


# reraise=True on every entrypoint: after the job's own transient-retry logic
# gives up, the exception propagates so RQ records it in the FailedJobRegistry
# (dead-letter) and applies the RQ retry policy configured at enqueue time.


def run_seo_run(run_id: str, tenant_id: str) -> None:
    from app.jobs.seo_run_jobs import run_seo_run_background

    asyncio.run(run_seo_run_background(_uuid(run_id), _uuid(tenant_id), reraise=True))


def dispatch_code_fixes(connection_id: str, tenant_id: str) -> None:
    from app.jobs.brain_jobs import dispatch_code_fixes_background

    asyncio.run(dispatch_code_fixes_background(_uuid(connection_id), _uuid(tenant_id), reraise=True))


def run_brain_cycle(seo_run_id: str, project_id: str, tenant_id: str) -> None:
    from app.jobs.brain_jobs import run_brain_cycle_background

    asyncio.run(run_brain_cycle_background(_uuid(seo_run_id), _uuid(project_id), _uuid(tenant_id)))


def run_due_verifications(tenant_id: str | None = None) -> None:
    from app.jobs.verification_jobs import run_due_verifications_background

    asyncio.run(run_due_verifications_background(_uuid(tenant_id) if tenant_id else None, reraise=True))


def generate_daily_briefings(use_llm: bool = False) -> None:
    from app.jobs.briefing_jobs import generate_daily_briefings_background

    asyncio.run(generate_daily_briefings_background(use_llm=use_llm, reraise=True))
