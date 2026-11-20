"""Closing out runs whose worker is gone.

A run is executed by one process. When that process disappears — a restart, a
deploy, an OOM kill — nothing noticed: the row kept saying `running` and the
dashboard kept spinning on a run that would never move again. These cover the
two halves of the fix, since either alone is wrong: the reaper without the
heartbeat would kill healthy long runs, and the heartbeat without the reaper
would record liveness nobody reads.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.seo_run import SeoRun, SeoRunStatus
from app.services.seo_run import SEO_RUN_HEARTBEAT_SECONDS, fail_stale_runs


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeDb:
    """Returns whatever the test put in `rows` and records the commit."""

    def __init__(self, rows):
        self.rows = rows
        self.committed = False

    async def execute(self, _query):
        return FakeResult(self.rows)

    async def commit(self):
        self.committed = True


def make_run(minutes_since_update: float):
    run = SeoRun()
    run.status = SeoRunStatus.running
    run.updated_at = datetime.utcnow() - timedelta(minutes=minutes_since_update)
    run.current_stage = None
    run.error_message = None
    return run


@pytest.mark.asyncio
async def test_a_silent_run_is_closed_with_a_message_that_explains_itself():
    """The operator needs to know it was the worker, not their site."""
    run = make_run(minutes_since_update=40)
    db = FakeDb([run])

    closed = await fail_stale_runs(db, stale_after_seconds=900)

    assert closed == 1
    assert run.status == SeoRunStatus.failed
    assert "restarted" in run.error_message
    assert "start a new run" in run.error_message.lower()
    assert db.committed


@pytest.mark.asyncio
async def test_nothing_to_close_commits_nothing():
    db = FakeDb([])

    assert await fail_stale_runs(db, stale_after_seconds=900) == 0
    assert not db.committed


def test_the_stale_window_is_many_heartbeats_wide():
    """The reaper is only safe because a live run reports in far more often than
    it needs to. If these ever converge, healthy runs start getting killed."""
    from app.core.config import settings

    assert settings.SEO_RUN_STALE_AFTER_SECONDS >= SEO_RUN_HEARTBEAT_SECONDS * 10


@pytest.mark.asyncio
async def test_the_reaper_can_be_scoped_to_one_tenant():
    """The read path reaps for the tenant doing the reading, not the whole
    table: a dashboard request must not do work proportional to every customer."""
    run = make_run(minutes_since_update=40)
    db = FakeDb([run])

    closed = await fail_stale_runs(db, stale_after_seconds=900, tenant_id=uuid4())

    assert closed == 1


@pytest.mark.asyncio
async def test_a_failing_reap_never_breaks_a_read():
    """Showing a slightly stale run beats failing the dashboard that asked for
    it, so the lazy reap swallows its own errors."""
    from app.services.seo_run import SeoRunService

    class ExplodingDb(FakeDb):
        async def execute(self, _query):
            raise RuntimeError("database is having a bad day")

    service = SeoRunService.__new__(SeoRunService)
    service.db = ExplodingDb([])

    await service._reap_before_reading(uuid4())
