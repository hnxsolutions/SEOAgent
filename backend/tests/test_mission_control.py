"""Tests for MissionControlService composition helpers."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.mission_control import MissionControlService


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class _FakeDB:
    def __init__(self, results):
        self._results = list(results)

    async def execute(self, _q):
        return _Result(self._results.pop(0) if self._results else [])


def test_scheduler_status_reports_config():
    status = MissionControlService(db=object())._scheduler_status()
    assert status["status"] == "configured"
    assert "interval_seconds" in status and "tick_limit" in status


def test_enum_unwraps_enum_values():
    assert MissionControlService._enum(SimpleNamespace(value="x")) == "x"
    assert MissionControlService._enum("plain") == "plain"
    assert MissionControlService._enum(None) is None


@pytest.mark.asyncio
async def test_current_activity_idle_when_no_running_run():
    service = MissionControlService(_FakeDB([[]]))  # no running run
    result = await service._current_activity(uuid4(), [])
    assert result == {"active": False, "task": "idle", "project_id": None}


@pytest.mark.asyncio
async def test_current_activity_computes_progress():
    project_id = uuid4()
    running = SimpleNamespace(
        project_id=project_id,
        current_stage=SimpleNamespace(value="content_optimization"),
        stage_statuses={
            "crawl": "completed", "audit": "completed", "semantic_index": "completed",
            "content_optimization": "running", "planner": "pending",
        },
    )
    service = MissionControlService(_FakeDB([[running]]))
    projects = [SimpleNamespace(id=project_id, name="Novako")]
    result = await service._current_activity(uuid4(), projects)
    assert result["active"] is True
    assert result["project_name"] == "Novako"
    assert result["current_stage"] == "content_optimization"
    assert result["progress_pct"] == 60  # 3 of 5 completed
