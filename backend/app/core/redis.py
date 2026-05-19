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


async def init_redis():
    """Initialize Redis connection"""
    global redis_client
    try:
        redis_client = redis.from_url(
            settings.get_redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        # Test connection
        await redis_client.ping()
        logger.info("Redis connection established successfully")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise


async def close_redis():
    """Close Redis connection"""
    global redis_client
    if redis_client:
        await redis_client.close()
        logger.info("Redis connection closed")


async def get_redis() -> redis.Redis:
    """Get Redis client instance"""
    if redis_client is None:
        await init_redis()
    return redis_client