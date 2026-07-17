"""Background job entry points for one-click / autonomous SEO runs.

Kept separate from the API routes so both the manual ``/seo-run`` endpoint and
autonomous triggers (e.g. auto-run on project creation, scheduler) can enqueue a
full pipeline run without importing route modules into one another.
"""
from uuid import UUID

import structlog

from app.core.database import get_db_session
from app.services.seo_run import SeoRunService
from app.services.telemetry import run_with_telemetry

logger = structlog.get_logger(__name__)


async def run_seo_run_background(run_id: UUID, tenant_id: UUID) -> None:
    """Execute a one-click SEO run with its own fresh DB session, recorded in
    scheduler telemetry (crawl->audit->semantic->content->planner)."""
    async def _body():
        db = get_db_session()
        try:
            await SeoRunService(db).execute_run(run_id, tenant_id)
        finally:
            await db.close()

    await run_with_telemetry(
        "seo_run", "pipeline", _body,
        tenant_id=tenant_id, project_id=None,
        # A full pipeline is expensive; don't auto-retry the whole thing.
        max_retries=0,
    )
