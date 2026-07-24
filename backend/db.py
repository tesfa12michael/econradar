"""Database engine and session management.

Uses psycopg3 as the single Postgres driver for both the async API engine
(`postgresql+psycopg://`) and — separately — APScheduler's sync jobstore
(see scheduler/). Engine creation is lazy: nothing connects at import time, so
the app and the test suite import cleanly without a database.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import settings
from logging_config import get_logger

logger = get_logger(__name__)

# Postgres URL schemes we might receive from Supabase / env, longest first so a
# prefix match doesn't shadow a more specific driver.
_KNOWN_SCHEMES = (
    "postgresql+psycopg",
    "postgresql+asyncpg",
    "postgresql+psycopg2",
    "postgresql",
    "postgres",
)


def normalize_db_url(url: str) -> str:
    """Force any Postgres URL onto the psycopg3 driver (works sync AND async)."""
    for scheme in _KNOWN_SCHEMES:
        prefix = scheme + "://"
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use."""
    global _engine
    if _engine is None:
        if not settings.database_url:
            raise RuntimeError(
                "DATABASE_URL is not set — cannot create a database engine. "
                "Set it in .env (see .env.example)."
            )
        _engine = create_async_engine(
            normalize_db_url(settings.database_url),
            pool_pre_ping=True,  # transparently recycle Render/Supabase-dropped conns
            pool_size=5,
            max_overflow=5,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped async session."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def check_db() -> bool:
    """Cheap connectivity probe for /health. Never raises — returns False on failure."""
    if not settings.database_url:
        return False
    try:
        async with get_session_factory()() as session:
            await session.execute(text("select 1"))
        return True
    except Exception as exc:
        logger.warning("Database health check failed: %s", exc)
        return False


async def dispose_engine() -> None:
    """Dispose the engine on shutdown (called from the FastAPI lifespan)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
