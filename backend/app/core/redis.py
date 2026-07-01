"""
SEO Agent SaaS - Redis Configuration
"""
import redis.asyncio as redis
from typing import Optional
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

# Redis client instance
redis_client: Optional[redis.Redis] = None
redis_available: bool = False
redis_error: Optional[str] = None

REDIS_UNAVAILABLE_MESSAGE = "Redis is not available. Start Redis to use queued/background jobs."


class RedisUnavailableError(RuntimeError):
    """Raised when a Redis-backed queue operation is requested but Redis is unavailable."""


async def init_redis():
    """Initialize Redis connection"""
    global redis_client, redis_available, redis_error
    try:
        redis_client = redis.from_url(
            settings.get_redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        # Test connection
        await redis_client.ping()
        redis_available = True
        redis_error = None
        logger.info("Redis connection established successfully")
    except Exception as e:
        redis_available = False
        redis_error = str(e)
        if redis_client:
            try:
                await redis_client.close()
            except Exception:
                pass
        redis_client = None
        if settings.REDIS_REQUIRED:
            logger.error("Redis is required but unavailable", error=redis_error)
            raise
        logger.warning(REDIS_UNAVAILABLE_MESSAGE, error=redis_error)


async def close_redis():
    """Close Redis connection"""
    global redis_client, redis_available
    if redis_client:
        await redis_client.close()
        redis_available = False
        logger.info("Redis connection closed")


async def get_redis() -> redis.Redis:
    """Get Redis client instance"""
    if redis_client is None:
        await init_redis()
    if redis_client is None or not redis_available:
        raise RedisUnavailableError(REDIS_UNAVAILABLE_MESSAGE)
    return redis_client


def get_redis_status() -> dict:
    """Return a dashboard/health friendly Redis status without reconnecting."""
    return {
        "available": redis_available,
        "required": settings.REDIS_REQUIRED,
        "url": settings.get_redis_url,
        "message": None if redis_available else REDIS_UNAVAILABLE_MESSAGE,
        "error": redis_error,
    }
