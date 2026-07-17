"""Tests for the telemetry retry classifier and retry orchestration."""
import asyncio
from uuid import uuid4

import pytest

from app.services import telemetry as tel
from app.services.telemetry import is_retryable, run_with_telemetry


@pytest.mark.parametrize("exc,expected", [
    (TimeoutError("read timed out"), True),
    (asyncio.TimeoutError(), True),
    (Exception("Ollama is not reachable at host.docker.internal"), True),
    (Exception("Connection reset by peer"), True),
    (Exception("503 Service Unavailable"), True),
    (Exception("GitHub API rate limit"), True),
    (ValueError("validation failed: invalid input"), False),
    (Exception("403 Forbidden: permission denied"), False),
    (Exception("Project not found"), False),
    (Exception("missing configuration for GSC"), False),
])
def test_is_retryable_classification(exc, expected):
    assert is_retryable(exc) is expected


@pytest.fixture
def _no_db(monkeypatch):
    """Stub telemetry persistence so retry orchestration can be tested without a DB."""
    async def fake_create(*a, **k):
        return uuid4()

    async def fake_write(*a, **k):
        return None

    monkeypatch.setattr(tel, "_create", fake_create)
    monkeypatch.setattr(tel, "_write", fake_write)


@pytest.mark.asyncio
async def test_retries_transient_then_succeeds(_no_db):
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("temporarily unavailable")
        return "ok"

    result = await run_with_telemetry("t", "test", flaky, max_retries=3, base_delay=0)
    assert result == "ok"
    assert calls["n"] == 3  # two retries then success


@pytest.mark.asyncio
async def test_does_not_retry_deterministic_error(_no_db):
    calls = {"n": 0}

    async def bad():
        calls["n"] += 1
        raise ValueError("validation failed: invalid")

    result = await run_with_telemetry("t", "test", bad, max_retries=3, base_delay=0)
    assert result is None       # swallowed (reraise=False)
    assert calls["n"] == 1      # no retries for a deterministic error


@pytest.mark.asyncio
async def test_stops_after_max_retries(_no_db):
    calls = {"n": 0}

    async def always_timeout():
        calls["n"] += 1
        raise TimeoutError("timeout")

    result = await run_with_telemetry("t", "test", always_timeout, max_retries=2, base_delay=0)
    assert result is None
    assert calls["n"] == 3      # initial + 2 retries


@pytest.mark.asyncio
async def test_reraise_propagates(_no_db):
    async def bad():
        raise ValueError("invalid")

    with pytest.raises(ValueError):
        await run_with_telemetry("t", "test", bad, max_retries=0, base_delay=0, reraise=True)
