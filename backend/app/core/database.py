"""
SEO Agent SaaS - Database Configuration
"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import create_engine, text
from typing import AsyncGenerator
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


def make_async_database_url(url: str) -> str:
    """Return an asyncpg-compatible URL for SQLAlchemy async engines."""
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    return url


def make_sync_database_url(url: str) -> str:
    """Return a sync PostgreSQL URL for Alembic and sync utilities."""
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


ASYNC_DATABASE_URL = make_async_database_url(settings.get_database_url)
SYNC_DATABASE_URL = make_sync_database_url(settings.get_database_url)

# Create async engine
engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=settings.APP_DEBUG,
    hide_parameters=True,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=40,
)

# Create async session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Sync session factory (for Alembic migrations)
sync_engine = create_engine(
    SYNC_DATABASE_URL,
    echo=settings.APP_DEBUG,
    hide_parameters=True,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=sync_engine,
)


class Base(DeclarativeBase):
    """Base class for all database models"""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting async database session"""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def get_db_session() -> AsyncSession:
    """Create an async session for background tasks."""
    return async_session_maker()


async def init_db():
    """Initialize database connection"""
    try:
        # Test connection
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            logger.info("Database connection established successfully")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise


async def close_db():
    """Close database connection"""
    await engine.dispose()
    logger.info("Database connection closed")
