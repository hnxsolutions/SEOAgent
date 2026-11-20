"""Default recurring schedules for a newly added domain.

Adding a domain used to start exactly one SEO run and then stop forever: the
six schedule types existed, the scheduler knew how to execute them, and nothing
ever created a row. The whole autonomous loop was one `POST /schedules` away
from running and nobody made that call. This module closes that gap — a project
provisions its own cadence the moment it exists.

Two rules shape everything here:

**Declarative, not imperative.** The plan below is data. A reviewer can read it
and know exactly what a new domain will do for the next month without tracing
any code, and changing the cadence is an edit to a list rather than to logic.

**Idempotent by construction.** Provisioning is called on project creation, by
backfill, and by anything that repairs a project later; it must be safe to run
a hundred times. Existing rows are matched on the natural key — project, type
and the day the job lands on — and skipped. A unique index backs the same key
in the database, so two concurrent calls cannot both win.

Nothing here talks to an external service, and no schedule costs money to run:
every job it provisions is served by Search Console, the project's own crawl,
or the local model.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scheduler import SeoSchedule, SeoScheduleFrequency, SeoScheduleType

logger = structlog.get_logger(__name__)


# Weekday numbers follow `datetime.weekday()`: Monday is 0.
MON, TUE, WED, THU, FRI = 0, 1, 2, 3, 4

#: How many articles a week a project drafts unless it says otherwise.
DEFAULT_BLOGS_PER_WEEK = 2
MAX_BLOGS_PER_WEEK = 7

#: The weekdays drafting lands on, in the order they are taken up. Spread
#: across the week on purpose: three drafts queued on one morning is three
#: articles reviewed carelessly in one sitting.
BLOG_DAYS: Sequence[int] = (WED, FRI, MON, TUE, THU, 5, 6)


@dataclass(frozen=True)
class ScheduleSpec:
    """One schedule to create. Pure data — see the module docstring."""

    schedule_type: SeoScheduleType
    frequency: SeoScheduleFrequency
    name: str
    hour: int
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None

    def values(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "name": self.name,
            "schedule_type": self.schedule_type,
            "frequency": self.frequency,
            "day_of_week": self.day_of_week,
            "day_of_month": self.day_of_month,
            "hour": self.hour,
            "minute": 0,
            "timezone": "UTC",
            "is_enabled": True,
        }


def _daily(schedule_type: SeoScheduleType, name: str, hour: int) -> ScheduleSpec:
    return ScheduleSpec(schedule_type, SeoScheduleFrequency.daily, name, hour)


def _weekly(schedule_type: SeoScheduleType, name: str, hour: int, day: int) -> ScheduleSpec:
    return ScheduleSpec(schedule_type, SeoScheduleFrequency.weekly, name, hour, day_of_week=day)


def _monthly(schedule_type: SeoScheduleType, name: str, hour: int, day: int) -> ScheduleSpec:
    return ScheduleSpec(schedule_type, SeoScheduleFrequency.monthly, name, hour, day_of_month=day)


#: The cadence every new domain starts on.
#:
#: Hours are staggered rather than all at 09:00 so that a tenant with twenty
#: projects does not fire twenty crawls, twenty audits and twenty model calls
#: into the same minute. The heavy jobs (full audit, deep audit) sit at night.
BASE_PLAN: Sequence[ScheduleSpec] = (
    # Daily — cheap, data-only, keeps the picture current.
    _daily(SeoScheduleType.daily_gsc_sync, "Daily Search Console sync", hour=6),
    _daily(SeoScheduleType.daily_health_monitor, "Daily site health & change detection", hour=7),
    # Weekly — the working week.
    _weekly(SeoScheduleType.content_opportunity_scan, "Weekly content opportunity scan", hour=8, day=MON),
    _weekly(SeoScheduleType.weekly_full_seo, "Weekly full SEO audit", hour=2, day=TUE),
    _weekly(SeoScheduleType.weekly_repo_scan, "Weekly code scan for SEO fixes", hour=3, day=TUE),
    _weekly(SeoScheduleType.weekly_indexing_monitor, "Weekly indexing monitor", hour=5, day=WED),
    _weekly(SeoScheduleType.weekly_internal_link_scan, "Weekly internal linking scan", hour=4, day=THU),
    _weekly(SeoScheduleType.weekly_content_performance, "Weekly content performance review", hour=8, day=FRI),
    # Monthly — strategy, not maintenance.
    _monthly(SeoScheduleType.monthly_deep_audit, "Monthly deep SEO audit", hour=1, day=1),
    _monthly(SeoScheduleType.monthly_content_strategy, "Monthly content strategy review", hour=9, day=2),
)


def plan_for(blogs_per_week: int = DEFAULT_BLOGS_PER_WEEK) -> List[ScheduleSpec]:
    """The full plan: the fixed cadence plus one drafting slot per article.

    Drafting is modelled as N weekly schedules on different days rather than one
    schedule with a count. It reuses the existing weekly machinery unchanged,
    each slot can be moved or disabled on its own, and "how many articles a week
    does this project write" stays answerable by counting rows.
    """
    count = max(0, min(int(blogs_per_week), MAX_BLOGS_PER_WEEK))
    blogs = [
        _weekly(
            SeoScheduleType.blog_generation,
            f"Blog drafting slot {index + 1}",
            hour=9,
            day=BLOG_DAYS[index],
        )
        for index in range(count)
    ]
    return list(BASE_PLAN) + blogs


class ScheduleProvisioningService:
    """Creates (and repairs) the default schedule set for a project."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def provision(
        self,
        project_id: UUID,
        tenant_id: UUID,
        *,
        blogs_per_week: int = DEFAULT_BLOGS_PER_WEEK,
        commit: bool = True,
    ) -> Dict[str, Any]:
        """Create every missing schedule for this project. Safe to re-run.

        Returns what it did rather than raising on partial success: a project
        whose schedules are half-created is still better off than one with none,
        and the caller (project creation) must never fail because of this.
        """
        from app.services.scheduler import SchedulerService

        scheduler = SchedulerService(self.db)
        existing = await self._existing_keys(project_id, tenant_id)

        created: List[str] = []
        skipped: List[str] = []

        for spec in plan_for(blogs_per_week):
            key = (spec.schedule_type.value, spec.day_of_week, spec.day_of_month)
            if key in existing:
                skipped.append(spec.name)
                continue

            values = spec.values(project_id, tenant_id)
            values["next_run_at"] = scheduler.calculate_next_run(values)
            try:
                # A savepoint, so that losing a race on the unique index costs
                # this one schedule rather than every schedule created so far.
                async with self.db.begin_nested():
                    self.db.add(SeoSchedule(**values))
            except IntegrityError:
                skipped.append(spec.name)
                continue

            existing.add(key)
            created.append(spec.name)

        if commit:
            await self.db.commit()

        logger.info(
            "schedules_provisioned",
            project_id=str(project_id),
            created=len(created),
            skipped=len(skipped),
            blogs_per_week=blogs_per_week,
        )
        return {
            "project_id": str(project_id),
            "created_count": len(created),
            "skipped_count": len(skipped),
            "created": created,
            "skipped": skipped,
        }

    async def set_blogs_per_week(
        self,
        project_id: UUID,
        tenant_id: UUID,
        blogs_per_week: int,
        *,
        commit: bool = True,
    ) -> Dict[str, Any]:
        """Change how many articles a week this project drafts.

        Adding slots creates them; removing slots disables the extras rather
        than deleting them, so the history of what ran on that day survives and
        turning the cadence back up re-enables the same rows.
        """
        target = max(0, min(int(blogs_per_week), MAX_BLOGS_PER_WEEK))
        wanted_days = set(BLOG_DAYS[:target])

        rows = await self._blog_slots(project_id, tenant_id)
        scheduler = None
        enabled = 0
        disabled = 0

        for row in rows:
            should_run = row.day_of_week in wanted_days
            if should_run and not row.is_enabled:
                if scheduler is None:
                    from app.services.scheduler import SchedulerService

                    scheduler = SchedulerService(self.db)
                row.is_enabled = True
                row.next_run_at = scheduler.calculate_next_run(row)
                enabled += 1
            elif not should_run and row.is_enabled:
                row.is_enabled = False
                row.next_run_at = None
                disabled += 1

        # Any slot the project has never had yet.
        result = await self.provision(
            project_id, tenant_id, blogs_per_week=target, commit=False
        )

        if commit:
            await self.db.commit()

        return {
            "blogs_per_week": target,
            "slots_enabled": enabled,
            "slots_disabled": disabled,
            "slots_created": result["created_count"],
        }

    async def _existing_keys(self, project_id: UUID, tenant_id: UUID) -> set:
        result = await self.db.execute(
            select(
                SeoSchedule.schedule_type,
                SeoSchedule.day_of_week,
                SeoSchedule.day_of_month,
            ).where(
                SeoSchedule.project_id == project_id,
                SeoSchedule.tenant_id == tenant_id,
            )
        )
        return {
            (getattr(row[0], "value", row[0]), row[1], row[2]) for row in result.all()
        }

    async def _blog_slots(self, project_id: UUID, tenant_id: UUID) -> List[SeoSchedule]:
        result = await self.db.execute(
            select(SeoSchedule).where(
                SeoSchedule.project_id == project_id,
                SeoSchedule.tenant_id == tenant_id,
                SeoSchedule.schedule_type == SeoScheduleType.blog_generation,
            )
        )
        return list(result.scalars().all())
