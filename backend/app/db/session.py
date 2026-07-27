"""Async engine / session factory and the FastAPI session dependency."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, settings


def enable_sqlite_foreign_keys(engine: AsyncEngine) -> None:
    """Turn on foreign-key enforcement for SQLite connections.

    SQLite ignores ``ON DELETE CASCADE`` unless the pragma is set per
    connection. Without this, deleting a device would leave its crash reports
    orphaned on SQLite while cascading correctly on PostgreSQL — exactly the
    kind of divergence that makes a test suite lie about production.
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragma(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


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

    engine = create_async_engine(url, **kwargs)
    if url.startswith("sqlite"):
        enable_sqlite_foreign_keys(engine)
    return engine


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
