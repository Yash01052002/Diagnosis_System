"""Async engine / session factory and the FastAPI session dependency."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, settings


def create_engine(config: Settings | None = None) -> AsyncEngine:
    """Build the async engine for ``config``.

    SQLite (used by tests) does not support connection pool sizing, so those
    options are only applied for server-side databases.
    """
    cfg = config or settings
    url = cfg.sqlalchemy_database_uri
    kwargs: dict[str, Any] = {
        "echo": cfg.DB_ECHO,
        "future": True,
        "pool_pre_ping": True,
    }
    if not url.startswith("sqlite"):
        kwargs["pool_size"] = cfg.DB_POOL_SIZE
        kwargs["max_overflow"] = cfg.DB_MAX_OVERFLOW
        kwargs["pool_recycle"] = 1800
    return create_async_engine(url, **kwargs)


engine: AsyncEngine = create_engine()

SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped session.

    The unit of work is owned here: handlers never commit implicitly on error,
    and the session is always closed.
    """
    async with SessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def dispose_engine() -> None:
    """Close all pooled connections (called on application shutdown)."""
    await engine.dispose()
