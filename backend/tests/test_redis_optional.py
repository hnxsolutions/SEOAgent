import pytest
from fastapi import FastAPI

from app.core import redis as redis_module


class FailingRedisClient:
    async def ping(self):
        raise ConnectionError("localhost:6379 connection refused")

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_init_redis_does_not_fail_when_optional(monkeypatch):
    monkeypatch.setattr(redis_module.settings, "REDIS_REQUIRED", False)
    monkeypatch.setattr(redis_module.redis, "from_url", lambda *args, **kwargs: FailingRedisClient())
    redis_module.redis_client = None
    redis_module.redis_available = False
    redis_module.redis_error = None

    await redis_module.init_redis()
    status = redis_module.get_redis_status()

    assert status["available"] is False
    assert status["required"] is False
    assert "Start Redis" in status["message"]
    assert "connection refused" in status["error"]


@pytest.mark.asyncio
async def test_init_redis_required_mode_raises(monkeypatch):
    monkeypatch.setattr(redis_module.settings, "REDIS_REQUIRED", True)
    monkeypatch.setattr(redis_module.redis, "from_url", lambda *args, **kwargs: FailingRedisClient())
    redis_module.redis_client = None
    redis_module.redis_available = False
    redis_module.redis_error = None

    with pytest.raises(ConnectionError):
        await redis_module.init_redis()

    assert redis_module.get_redis_status()["required"] is True


@pytest.mark.asyncio
async def test_app_lifespan_continues_when_redis_optional(monkeypatch):
    from app import main as main_module

    async def noop():
        return None

    monkeypatch.setattr(redis_module.settings, "REDIS_REQUIRED", False)
    monkeypatch.setattr(redis_module.redis, "from_url", lambda *args, **kwargs: FailingRedisClient())
    monkeypatch.setattr(main_module, "init_db", noop)
    monkeypatch.setattr(main_module, "init_qdrant", noop)
    redis_module.redis_client = None
    redis_module.redis_available = False
    redis_module.redis_error = None

    async with main_module.lifespan(FastAPI()):
        assert redis_module.get_redis_status()["available"] is False
