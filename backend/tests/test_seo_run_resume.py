"""Continuing a failed run from the stage that stopped.

A run that died in content was restarted from the crawl: an eight-minute crawl,
an audit and twenty minutes of embeddings were all paid for again, despite being
finished and still sitting in the database. On CPU-only hardware that is most of
an hour thrown away to reach the stage that actually needed attention.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.seo_run import SeoRun, SeoRunStage, SeoRunStageStatus
from app.services.seo_run import SeoRunService


def service() -> SeoRunService:
    return SeoRunService.__new__(SeoRunService)


def run_with(statuses: dict) -> SeoRun:
    run = SeoRun()
    run.id = uuid4()
    run.stage_statuses = statuses
    return run


@pytest.mark.asyncio
async def test_a_finished_stage_is_reused_not_repeated():
    run = run_with({"crawl": "completed"})
    worked = False

    async def work():
        nonlocal worked
        worked = True
        return "fresh"

    async def load():
        return "existing crawl"

    result = await service()._resume_or_run(run, SeoRunStage.crawl, work, load)

    assert result == "existing crawl"
    assert not worked, "a completed stage must not run again"


@pytest.mark.asyncio
async def test_an_unfinished_stage_runs():
    run = run_with({"crawl": "failed"})

    async def work():
        return "fresh"

    async def load():
        raise AssertionError("must not load a stage that did not complete")

    assert await service()._resume_or_run(run, SeoRunStage.crawl, work, load) == "fresh"


@pytest.mark.asyncio
async def test_a_stage_whose_result_vanished_is_re_run():
    """A completed status with nothing behind it is a bookkeeping error, not a
    result. Re-running is the safe reading; trusting the status would carry a
    None into the next stage."""
    run = run_with({"crawl": "completed"})

    async def work():
        return "fresh"

    async def load():
        return None

    assert await service()._resume_or_run(run, SeoRunStage.crawl, work, load) == "fresh"


@pytest.mark.asyncio
async def test_a_run_with_no_history_runs_everything():
    run = run_with({})

    async def work():
        return "fresh"

    async def load():
        raise AssertionError("nothing to load")

    assert await service()._resume_or_run(run, SeoRunStage.audit, work, load) == "fresh"


def test_stage_status_reads_the_stored_map():
    run = run_with({"semantic_index": SeoRunStageStatus.completed.value})

    assert SeoRunService._stage_status(run, SeoRunStage.semantic_index) == "completed"
    assert SeoRunService._stage_status(run, SeoRunStage.planner) is None


# --- choosing which stage to restart from -----------------------------------

class CommitOnlyDb:
    async def commit(self):
        pass

    async def refresh(self, _obj):
        pass


def service_with_db() -> SeoRunService:
    svc = SeoRunService.__new__(SeoRunService)
    svc.db = CommitOnlyDb()
    return svc


def completed_run() -> SeoRun:
    run = SeoRun()
    run.id = uuid4()
    run.stage_statuses = {
        "crawl": "completed",
        "audit": "completed",
        "semantic_index": "completed",
        "content_optimization": "failed",
        "planner": "pending",
    }
    run.stage_errors = {"content_optimization": "the model fell over"}
    run.error_message = "the model fell over"
    return run


@pytest.mark.asyncio
async def test_resuming_from_a_stage_keeps_everything_before_it():
    """The entire point: re-running content must not re-crawl the site, re-audit
    it and redo twenty minutes of embeddings that are finished and correct."""
    run = completed_run()

    await service_with_db().reset_from_stage(run, SeoRunStage.content_optimization)

    assert run.stage_statuses["crawl"] == "completed"
    assert run.stage_statuses["audit"] == "completed"
    assert run.stage_statuses["semantic_index"] == "completed"


@pytest.mark.asyncio
async def test_resuming_from_a_stage_redoes_it_and_everything_after():
    """A later stage's result was computed from the earlier one, so keeping it
    would mix old conclusions with new data."""
    run = completed_run()
    run.stage_statuses["planner"] = "completed"

    await service_with_db().reset_from_stage(run, SeoRunStage.semantic_index)

    for stage in ("semantic_index", "content_optimization", "planner"):
        assert run.stage_statuses[stage] == "pending", stage
    assert run.stage_statuses["crawl"] == "completed"


@pytest.mark.asyncio
async def test_resuming_clears_the_old_failure_message():
    """A stale error beside a stage that is about to run again reads as a fresh
    failure."""
    run = completed_run()

    await service_with_db().reset_from_stage(run, SeoRunStage.content_optimization)

    assert run.error_message is None
    assert "content_optimization" not in run.stage_errors


@pytest.mark.asyncio
async def test_resuming_from_the_first_stage_redoes_everything():
    run = completed_run()

    await service_with_db().reset_from_stage(run, SeoRunStage.crawl)

    assert all(value == "pending" for value in run.stage_statuses.values())


@pytest.mark.asyncio
async def test_completed_is_not_a_stage_you_can_resume_from():
    """It is a terminal marker in the enum, not a step with work behind it."""
    with pytest.raises(ValueError):
        await service_with_db().reset_from_stage(completed_run(), SeoRunStage.completed)


@pytest.mark.asyncio
async def test_the_run_points_at_the_stage_it_will_restart_from():
    run = completed_run()

    await service_with_db().reset_from_stage(run, SeoRunStage.audit)

    assert run.current_stage == SeoRunStage.audit


@pytest.mark.asyncio
async def test_a_running_run_cannot_be_reset():
    """Resetting mid-flight corrupts the run from both ends: the worker carries
    on against stage statuses moved underneath it, and a second worker starts
    the same stage. The visible symptom was a content stage already past 38
    pages whose card read "Queued"."""
    from app.models.seo_run import SeoRunStatus

    run = completed_run()
    run.status = SeoRunStatus.running

    with pytest.raises(ValueError, match="still going"):
        await service_with_db().reset_from_stage(run, SeoRunStage.content_optimization)

    # And nothing was changed on the way out.
    assert run.stage_statuses["content_optimization"] == "failed"


@pytest.mark.asyncio
async def test_a_failed_run_can_still_be_reset():
    from app.models.seo_run import SeoRunStatus

    run = completed_run()
    run.status = SeoRunStatus.failed

    await service_with_db().reset_from_stage(run, SeoRunStage.content_optimization)

    assert run.stage_statuses["content_optimization"] == "pending"
