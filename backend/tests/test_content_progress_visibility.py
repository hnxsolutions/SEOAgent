"""The content stage has to be watchable while it runs.

`total_pages` and `total_suggestions` used to be written once, by `finish_run`,
at the very end. Until then the run reported zeros however much work it had
done, so the dashboard showed "Running", a spinner and nothing else for an hour.
With a stage that can genuinely stall on this stack, an operator could not tell
progress from a hang — which is exactly the complaint this addresses.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import settings
from app.services.content_optimization import ContentOptimizationService


class RecordingDb:
    """Captures what the run looked like at each commit."""

    def __init__(self, run):
        self.run = run
        self.snapshots: list[tuple[int, int, int]] = []

    async def commit(self):
        self.snapshots.append(
            (self.run.progress, self.run.total_pages, self.run.total_suggestions)
        )


def make_service(run):
    service = ContentOptimizationService.__new__(ContentOptimizationService)
    service.db = RecordingDb(run)
    return service


@pytest.mark.asyncio
async def test_progress_is_published_before_the_run_finishes():
    run = SimpleNamespace(id=uuid4(), progress=0, total_pages=0, total_suggestions=0)
    service = make_service(run)

    await service._publish_progress(run, 5, analysed=0, total=40, suggestions=0)
    await service._publish_progress(run, 50, analysed=20, total=40, suggestions=63)

    assert service.db.snapshots == [(5, 0, 0), (50, 20, 63)]


@pytest.mark.asyncio
async def test_counts_reflect_work_done_not_the_final_total():
    """The number the dashboard reads must be what has actually been found so
    far, so it climbs visibly instead of sitting at zero."""
    run = SimpleNamespace(id=uuid4(), progress=0, total_pages=0, total_suggestions=0)
    service = make_service(run)

    await service._publish_progress(run, 30, analysed=12, total=40, suggestions=31)

    assert run.total_pages == 12
    assert run.total_suggestions == 31


@pytest.mark.asyncio
async def test_progress_never_claims_completion_early():
    """95 is the ceiling while working; 100 belongs to the completion path, so a
    run can never look finished while it is still generating."""
    run = SimpleNamespace(id=uuid4(), progress=0, total_pages=0, total_suggestions=0)
    service = make_service(run)

    await service._publish_progress(run, 400, analysed=40, total=40, suggestions=99)

    assert run.progress == 95


def test_concurrency_is_a_small_measured_degree():
    """Measured here: at 4 Ollama cores concurrency made throughput worse; at 8,
    two at a time was best and four was worse again. A large value would be a
    guess that costs speed rather than gaining it."""
    assert 1 <= settings.CONTENT_LLM_CONCURRENCY <= 3
