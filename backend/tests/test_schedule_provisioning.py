"""Automatic schedule provisioning, and the idempotency it depends on.

Provisioning runs on every project creation and on any later repair, so
"running it twice does nothing the second time" is not a nicety — without it a
project accumulates a duplicate audit, a duplicate crawl and a duplicate
drafting slot on every call. These tests use an in-memory fake rather than a
database so they run in the normal suite, and the behaviour they pin is the
service-level half of the guarantee; the unique index in migration 0044 is the
other half.
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.scheduler import SeoScheduleFrequency, SeoScheduleType
from app.services.schedule_provisioning import (
    BASE_PLAN,
    BLOG_DAYS,
    DEFAULT_BLOGS_PER_WEEK,
    MAX_BLOGS_PER_WEEK,
    ScheduleProvisioningService,
    plan_for,
)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


class FakeNested:
    """Stands in for `db.begin_nested()` — a context manager that does nothing."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class FakeDB:
    """Records what was added; answers the one SELECT the service makes."""

    def __init__(self, existing_rows=None, blog_rows=None):
        self.added = []
        self.committed = 0
        self._existing = existing_rows or []
        self._blog_rows = blog_rows or []
        self._select_count = 0

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed += 1

    async def flush(self):
        return None

    def begin_nested(self):
        return FakeNested()

    async def execute(self, _query):
        # The service makes two different reads; the key lookup comes first and
        # the blog-slot lookup only from set_blogs_per_week.
        self._select_count += 1
        if self._blog_rows and self._select_count == 1:
            return FakeResult(self._blog_rows)
        return FakeResult(self._existing)


def schedule_row(schedule_type, day_of_week=None, day_of_month=None):
    return (schedule_type, day_of_week, day_of_month)


# --------------------------------------------------------------------------
# The plan itself
# --------------------------------------------------------------------------

def test_plan_covers_every_requested_cadence():
    types = {spec.schedule_type for spec in plan_for(2)}
    for required in (
        SeoScheduleType.daily_gsc_sync,
        SeoScheduleType.daily_health_monitor,
        SeoScheduleType.content_opportunity_scan,
        SeoScheduleType.blog_generation,
        SeoScheduleType.weekly_full_seo,
        SeoScheduleType.weekly_repo_scan,
        SeoScheduleType.weekly_indexing_monitor,
        SeoScheduleType.weekly_internal_link_scan,
        SeoScheduleType.weekly_content_performance,
        SeoScheduleType.monthly_deep_audit,
        SeoScheduleType.monthly_content_strategy,
    ):
        assert required in types, f"{required.value} missing from the default plan"


def test_blog_slots_match_requested_cadence():
    for count in (0, 1, 2, 3, 5):
        slots = [s for s in plan_for(count) if s.schedule_type == SeoScheduleType.blog_generation]
        assert len(slots) == count


def test_blog_slots_land_on_different_days():
    """Three drafts queued on one morning is three articles reviewed carelessly."""
    slots = [s for s in plan_for(3) if s.schedule_type == SeoScheduleType.blog_generation]
    days = [s.day_of_week for s in slots]
    assert len(set(days)) == len(days)
    assert set(days).issubset(set(BLOG_DAYS))


def test_blog_cadence_is_clamped():
    assert len([s for s in plan_for(99) if s.schedule_type == SeoScheduleType.blog_generation]) == MAX_BLOGS_PER_WEEK
    assert len([s for s in plan_for(-5) if s.schedule_type == SeoScheduleType.blog_generation]) == 0


def test_every_spec_is_internally_consistent():
    for spec in plan_for(DEFAULT_BLOGS_PER_WEEK):
        if spec.frequency == SeoScheduleFrequency.weekly:
            assert spec.day_of_week is not None and 0 <= spec.day_of_week <= 6
            assert spec.day_of_month is None
        elif spec.frequency == SeoScheduleFrequency.monthly:
            assert spec.day_of_month is not None and 1 <= spec.day_of_month <= 28
            assert spec.day_of_week is None
        else:
            assert spec.day_of_week is None and spec.day_of_month is None
        assert 0 <= spec.hour <= 23


def test_heavy_jobs_run_outside_working_hours():
    """A full crawl at 09:00 competes with everything else the tick does."""
    heavy = {SeoScheduleType.weekly_full_seo, SeoScheduleType.monthly_deep_audit}
    for spec in BASE_PLAN:
        if spec.schedule_type in heavy:
            assert spec.hour <= 5, f"{spec.name} should run overnight"


# --------------------------------------------------------------------------
# Provisioning
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provision_creates_the_whole_plan_for_a_new_project():
    db = FakeDB(existing_rows=[])
    result = await ScheduleProvisioningService(db).provision(uuid4(), uuid4(), blogs_per_week=2)

    assert result["created_count"] == len(plan_for(2))
    assert result["skipped_count"] == 0
    assert len(db.added) == len(plan_for(2))
    assert db.committed == 1


@pytest.mark.asyncio
async def test_every_created_schedule_has_a_next_run():
    """A schedule with no next_run_at is never due, so it never runs."""
    db = FakeDB(existing_rows=[])
    await ScheduleProvisioningService(db).provision(uuid4(), uuid4(), blogs_per_week=1)

    assert db.added
    for schedule in db.added:
        assert schedule.next_run_at is not None
        assert schedule.is_enabled is True


@pytest.mark.asyncio
async def test_provision_is_idempotent():
    """The second call must create nothing — this is the whole point."""
    project_id, tenant_id = uuid4(), uuid4()
    existing = [
        schedule_row(spec.schedule_type.value, spec.day_of_week, spec.day_of_month)
        for spec in plan_for(2)
    ]
    db = FakeDB(existing_rows=existing)

    result = await ScheduleProvisioningService(db).provision(project_id, tenant_id, blogs_per_week=2)

    assert result["created_count"] == 0
    assert result["skipped_count"] == len(plan_for(2))
    assert db.added == []


@pytest.mark.asyncio
async def test_provision_fills_only_the_gaps():
    """A project half-provisioned by an older release is repaired, not doubled."""
    existing = [schedule_row(SeoScheduleType.daily_gsc_sync.value, None, None)]
    db = FakeDB(existing_rows=existing)

    result = await ScheduleProvisioningService(db).provision(uuid4(), uuid4(), blogs_per_week=2)

    assert result["created_count"] == len(plan_for(2)) - 1
    created_types = {s.schedule_type for s in db.added}
    assert SeoScheduleType.daily_gsc_sync not in created_types


@pytest.mark.asyncio
async def test_two_drafting_slots_are_not_confused_with_each_other():
    """Slots differ only by weekday, so the natural key must include it."""
    existing = [schedule_row(SeoScheduleType.blog_generation.value, BLOG_DAYS[0], None)]
    db = FakeDB(existing_rows=existing)

    await ScheduleProvisioningService(db).provision(uuid4(), uuid4(), blogs_per_week=2)

    blog_slots = [s for s in db.added if s.schedule_type == SeoScheduleType.blog_generation]
    assert len(blog_slots) == 1
    assert blog_slots[0].day_of_week == BLOG_DAYS[1]


@pytest.mark.asyncio
async def test_zero_blogs_per_week_still_provisions_seo_schedules():
    """Turning content off must not turn the SEO agent off."""
    db = FakeDB(existing_rows=[])
    result = await ScheduleProvisioningService(db).provision(uuid4(), uuid4(), blogs_per_week=0)

    assert result["created_count"] == len(BASE_PLAN)
    assert not any(s.schedule_type == SeoScheduleType.blog_generation for s in db.added)


@pytest.mark.asyncio
async def test_schedules_carry_the_owning_tenant_and_project():
    project_id, tenant_id = uuid4(), uuid4()
    db = FakeDB(existing_rows=[])
    await ScheduleProvisioningService(db).provision(project_id, tenant_id, blogs_per_week=1)

    for schedule in db.added:
        assert schedule.project_id == project_id
        assert schedule.tenant_id == tenant_id
