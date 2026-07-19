"""Background entry points for after-merge verification.

Kept separate so both the API (manual trigger) and the scheduler tick can drive
the verification loop with their own DB sessions.
"""
from typing import Optional
from uuid import UUID

import structlog

from app.core.database import get_db_session
from app.jobs.seo_run_jobs import run_seo_run_background
from app.services.verification import VerificationEngine

logger = structlog.get_logger(__name__)


async def run_due_verifications_background(tenant_id: Optional[UUID] = None, reraise: bool = False) -> None:
    from app.services.telemetry import run_with_telemetry

    await run_with_telemetry(
        "verification", "verification", lambda: _run_due_verifications(tenant_id),
        tenant_id=tenant_id, max_retries=1, reraise=reraise,
    )


async def _run_due_verifications(tenant_id: Optional[UUID] = None) -> None:
    """Start follow-up runs for due verifications, execute them, then reconcile.

    Reuses run_seo_run_background so the follow-up analysis is the exact same
    crawl->audit->semantic->content->planner pipeline as any other SEO run.
    """
    db = get_db_session()
    started_runs = []
    try:
        result = await VerificationEngine(db).run_due_verifications(tenant_id=tenant_id)
        started_runs = result.get("started_runs") or []
        logger.info("verification_due_processed", started=len(started_runs))
    except Exception:
        logger.exception("verification_due_failed")
    finally:
        await db.close()

    # Execute each freshly-started follow-up run to completion (same pipeline as
    # any SEO run), then reconcile the verifications that now have results.
    for entry in started_runs:
        try:
            await run_seo_run_background(UUID(entry["run_id"]), UUID(entry["tenant_id"]))
        except Exception:
            logger.exception("verification_followup_execute_failed", run_id=entry.get("run_id"))

    db2 = get_db_session()
    try:
        await VerificationEngine(db2).reconcile_running_verifications(tenant_id=tenant_id)
    except Exception:
        logger.exception("verification_reconcile_failed")
    finally:
        await db2.close()
