"""Background orchestration for the SEO brain full analysis cycle.

Composes existing services only (SeoRunService for crawl->audit->semantic->
content->planner, then robots + sitemap intelligence). Each step is guarded so
one failing stage never aborts the rest of the cycle.
"""
from uuid import UUID

import structlog

from app.core.database import get_db_session
from app.services.robots import RobotsIntelligenceService
from app.services.seo_run import SeoRunService
from app.services.sitemap import SitemapIntelligenceService

logger = structlog.get_logger(__name__)


async def run_brain_cycle_background(seo_run_id: UUID, project_id: UUID, tenant_id: UUID) -> None:
    """Execute the full brain cycle for a project with a fresh DB session."""
    db = get_db_session()
    try:
        # Stage 1-5: the existing one-click pipeline.
        try:
            await SeoRunService(db).execute_run(seo_run_id, tenant_id)
        except Exception:
            logger.exception("brain_cycle_seo_run_failed", seo_run_id=str(seo_run_id))

        # Stage: robots intelligence (public fetch; no credentials required).
        try:
            await RobotsIntelligenceService(db).analyze_project(project_id, tenant_id)
        except Exception:
            logger.exception("brain_cycle_robots_failed", project_id=str(project_id))

        # Stage: sitemap detection (public fetch; no credentials required).
        try:
            await SitemapIntelligenceService(db).detect(project_id, tenant_id)
        except Exception:
            logger.exception("brain_cycle_sitemap_failed", project_id=str(project_id))

        logger.info("brain_cycle_complete", project_id=str(project_id), seo_run_id=str(seo_run_id))
    finally:
        await db.close()
