"""Tests for per-stage pipeline telemetry recorder + status mapping."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.telemetry import JobStatus
from app.services.stage_telemetry import PIPELINE_STAGES, _coerce, record_stage


def test_pipeline_stage_order():
    assert PIPELINE_STAGES == ["crawl", "audit", "semantic_index", "content_optimization", "planner"]


def test_status_coercion():
    assert _coerce("running") == JobStatus.running
    assert _coerce("completed") == JobStatus.completed
    assert _coerce("failed") == JobStatus.failed
    assert _coerce("pending") == JobStatus.queued
    assert _coerce(SimpleNamespace(value="completed")) == JobStatus.completed
    assert _coerce("weird") == JobStatus.running  # safe default


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
        self.added = []
        self.commits = 0

    async def execute(self, _q):
        return _Result(self._results.pop(0) if self._results else [])

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        return None


@pytest.mark.asyncio
async def test_record_stage_creates_running_row():
    run = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), project_id=uuid4())
    db = _FakeDB([[]])  # no existing row
    await record_stage(db, run, "crawl", "running")
    assert len(db.added) == 1
    row = db.added[0]
    assert row.stage_name == "crawl"
    assert row.status == JobStatus.running
    assert row.started_at is not None
    assert db.commits == 1


@pytest.mark.asyncio
async def test_record_stage_completes_and_computes_duration():
    from datetime import datetime, timedelta

    run = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), project_id=uuid4())
    existing = SimpleNamespace(
        stage_name="crawl", status=JobStatus.running,
        started_at=datetime.utcnow() - timedelta(seconds=5),
        finished_at=None, duration_ms=None, error_message=None,
    )
    db = _FakeDB([[existing]])  # existing running row
    await record_stage(db, run, "crawl", "completed")
    assert existing.status == JobStatus.completed
    assert existing.finished_at is not None
    assert existing.duration_ms is not None and existing.duration_ms >= 4000
