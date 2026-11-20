"""A planner run that creates nothing is not a planner run that did nothing.

The planner upserts: a finding that already has a task is refreshed, and only a
genuinely new finding creates one. Run it again over an unchanged site and it
correctly creates zero — but `tasks_created` was the only number stored, so the
console showed "0 tasks created" beside a project holding 803 tasks, which reads
as a failure.
"""
from __future__ import annotations

import inspect

from app.models.planner import SeoPlannerRun
from app.repositories.planner import PlannerRepository
from app.schemas.planner import SeoPlannerRunResponse
from app.services.planner import PlannerService


def test_the_run_record_can_hold_a_refreshed_count():
    assert hasattr(SeoPlannerRun, "tasks_refreshed")


def test_the_api_exposes_it():
    assert "tasks_refreshed" in SeoPlannerRunResponse.model_fields


def test_the_repository_persists_it():
    signature = inspect.signature(PlannerRepository.finish_run)

    assert "tasks_refreshed" in signature.parameters


def test_refreshed_is_everything_touched_that_was_not_created():
    """The arithmetic that makes the number meaningful — and the clamp, so a
    bookkeeping slip can never report a negative count."""
    source = inspect.getsource(PlannerService.execute_run)

    assert "len(touched_tasks) - created_count" in source
    assert "max(" in source


def test_the_two_counts_are_reported_separately():
    """Summing them would hide the distinction this exists to show."""
    source = inspect.getsource(PlannerService.execute_run)

    assert "tasks_created=created_count" in source
    assert "tasks_refreshed=refreshed_count" in source
