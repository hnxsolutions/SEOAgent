"""Background job entry points for one-click / autonomous SEO runs.

Kept separate from the API routes so both the manual ``/seo-run`` endpoint and
autonomous triggers (e.g. auto-run on project creation, scheduler) can enqueue a
full pipeline run without importing route modules into one another.
"""
from uuid import UUID

import structlog

from app.core.database import get_db_session
from app.services.seo_run import SeoRunService

logger = structlog.get_logger(__name__)


async def run_seo_run_background(run_id: UUID, tenant_id: UUID) -> None:
    """Execute a one-click SEO run with its own fresh DB session."""
    db = get_db_session()
    try:
        service = SeoRunService(db)
        await service.execute_run(run_id, tenant_id)
    except Exception:  # pragma: no cover - defensive: never crash the worker/task
        logger.exception("seo_run_background_failed", run_id=str(run_id), tenant_id=str(tenant_id))
    finally:
        await db.close()
