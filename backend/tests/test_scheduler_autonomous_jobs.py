"""The autonomous schedule types the scheduler gained.

These jobs run unattended against live sites, so what matters is less that they
succeed than that they fail *safely*: an unconfigured project must be skipped
with a readable reason rather than raising and stopping the tick for every other
project in the deployment.
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.scheduler import (
    SeoSchedule,
    SeoScheduledRunStatus,
    SeoScheduleFrequency,
    SeoScheduleType,
)
from app.services.scheduler import SchedulerService


class FakeDB:
    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None


def make_schedule(schedule_type):
    return SeoSchedule(
        tenant_id=uuid4(),
        project_id=uuid4(),
        name=schedule_type.value,
        schedule_type=schedule_type,
        frequency=SeoScheduleFrequency.weekly,
        day_of_week=0,
        hour=9,
        minute=0,
        timezone="UTC",
        is_enabled=True,
    )


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "schedule_type,handler",
    [
        (SeoScheduleType.daily_health_monitor, "_run_health_monitor"),
        (SeoScheduleType.content_opportunity_scan, "_run_content_opportunity_scan"),
        (SeoScheduleType.blog_generation, "_run_blog_generation"),
        (SeoScheduleType.weekly_content_performance, "_run_content_performance"),
        (SeoScheduleType.weekly_internal_link_scan, "_run_internal_link_scan"),
        (SeoScheduleType.monthly_content_strategy, "_run_content_strategy"),
    ],
)
@pytest.mark.asyncio
async def test_every_new_type_dispatches_to_its_handler(schedule_type, handler, monkeypatch):
    """A type with no handler raises SchedulerError and the schedule never runs."""
    service = SchedulerService(FakeDB())
    called = {}

    async def fake_handler(schedule):
        called["schedule"] = schedule
        return {"status": SeoScheduledRunStatus.completed, "summary": {}}

    monkeypatch.setattr(service, handler, fake_handler)
    schedule = make_schedule(schedule_type)

    result = await service._execute_schedule_type(schedule)

    assert called["schedule"] is schedule
    assert result["status"] == SeoScheduledRunStatus.completed


# --------------------------------------------------------------------------
# Failing safely
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_internal_link_scan_skips_without_a_crawl():
    """No crawl means nothing to link between — a skip, not an exception."""
    service = SchedulerService(FakeDB())
    schedule = make_schedule(SeoScheduleType.weekly_internal_link_scan)

    import app.services.content_engine as content_engine

    original = content_engine.latest_completed_crawl

    async def no_crawl(*_args, **_kwargs):
        return None

    content_engine.latest_completed_crawl = no_crawl
    try:
        result = await service._run_internal_link_scan(schedule)
    finally:
        content_engine.latest_completed_crawl = original

    assert result["status"] == SeoScheduledRunStatus.skipped
    assert "No completed crawl" in result["summary"]["reason"]


@pytest.mark.asyncio
async def test_blog_generation_records_a_skip_when_nothing_is_worth_writing(monkeypatch):
    """Skipping a drafting slot is a correct outcome, not a failed job."""
    service = SchedulerService(FakeDB())
    schedule = make_schedule(SeoScheduleType.blog_generation)

    class NoTopics:
        def __init__(self, _db):
            pass

        async def draft_next(self, *_args, **_kwargs):
            return {"drafted": False, "reason": "No topic above the quality bar is waiting."}

    import app.services.content_engine as content_engine

    monkeypatch.setattr(content_engine, "ContentEngineService", NoTopics)

    result = await service._run_blog_generation(schedule)

    assert result["status"] == SeoScheduledRunStatus.skipped
    assert "quality bar" in result["error_message"]
    assert result["ids"] == {}


@pytest.mark.asyncio
async def test_blog_generation_reports_the_draft_it_made(monkeypatch):
    service = SchedulerService(FakeDB())
    schedule = make_schedule(SeoScheduleType.blog_generation)
    draft_id = str(uuid4())

    class OneDraft:
        def __init__(self, _db):
            pass

        async def draft_next(self, *_args, **_kwargs):
            return {"drafted": True, "draft_id": draft_id, "title": "An article", "seo_score": 86}

    import app.services.content_engine as content_engine

    monkeypatch.setattr(content_engine, "ContentEngineService", OneDraft)

    result = await service._run_blog_generation(schedule)

    assert result["status"] == SeoScheduledRunStatus.completed
    assert result["ids"]["blog_draft_id"] == draft_id
    # Nothing a scheduled job does may publish without a human.
    assert "publishing requires human approval" in result["summary"]["safety"]


@pytest.mark.asyncio
async def test_autonomous_jobs_never_claim_to_have_changed_the_site(monkeypatch):
    """Every summary states what was *not* done — these run unattended."""
    service = SchedulerService(FakeDB())

    class Stub:
        def __init__(self, _db):
            pass

        async def scan_opportunities(self, *_a, **_k):
            return {"topics_created": 0}

        async def review_performance(self, *_a, **_k):
            return {"articles": 0}

    import app.services.content_engine as content_engine

    monkeypatch.setattr(content_engine, "ContentEngineService", Stub)

    scan = await service._run_content_opportunity_scan(
        make_schedule(SeoScheduleType.content_opportunity_scan)
    )
    performance = await service._run_content_performance(
        make_schedule(SeoScheduleType.weekly_content_performance)
    )

    assert "safety" in scan["summary"]
    assert "safety" in performance["summary"]
    assert "Nothing was drafted or published" in scan["summary"]["safety"]
    assert "No content was changed" in performance["summary"]["safety"]
