"""Background job: automatically generate the daily executive briefing.

Called from the scheduler tick so an admin never has to click 'generate'. One
briefing per project per day (the service upserts, so re-running is safe).
"""
from datetime import date
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import select

from app.core.database import get_db_session
from app.models.briefing import DailyBriefing
from app.models.project import Project
from app.services.daily_briefing import DailyBriefingService

logger = structlog.get_logger(__name__)


async def generate_daily_briefings_background(use_llm: bool = True, limit: int = 200) -> int:
    """Generate today's briefing for every project that does not have one yet."""
    generated = 0
    db = get_db_session()
    try:
        projects = (await db.execute(select(Project).limit(limit))).scalars().all()
        today = date.today()
        for project in projects:
            exists = (await db.execute(
                select(DailyBriefing.id).where(
                    DailyBriefing.project_id == project.id,
                    DailyBriefing.briefing_date == today,
                )
            )).scalars().first()
            if exists:
                continue
            try:
                await DailyBriefingService(db).generate(project.id, project.tenant_id, use_llm=use_llm)
                generated += 1
            except Exception:
                logger.exception("daily_briefing_generate_failed", project_id=str(project.id))
    finally:
        await db.close()
    logger.info("daily_briefings_generated", generated=generated)
    return generated
