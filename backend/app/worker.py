"""Celery application.

Phase 1 registers only housekeeping tasks; crash ingestion and AI diagnosis
tasks are added in later phases. Start a worker with::

    celery -A app.worker.celery_app worker --loglevel=INFO
"""

from __future__ import annotations

import asyncio
from typing import Any

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

settings = get_settings()
configure_logging(settings)
logger = get_logger(__name__)

celery_app = Celery(
    "blackbox",
    broker=settings.celery_broker,
    backend=settings.celery_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=600,
    task_soft_time_limit=540,
    result_expires=86400,
    beat_schedule={
        "purge-expired-tokens": {
            "task": "app.worker.purge_expired_tokens",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)


@celery_app.task(name="app.worker.health_check")
def health_check() -> dict[str, str]:
    """Trivial task used to verify broker connectivity."""
    return {"status": "ok"}


@celery_app.task(name="app.worker.purge_expired_tokens")
def purge_expired_tokens() -> dict[str, Any]:
    """Delete refresh tokens whose expiry has passed.

    Celery tasks are synchronous, so the async repository call is driven by a
    dedicated event loop.
    """

    async def _run() -> int:
        from app.db.session import SessionFactory
        from app.repositories.user import RefreshTokenRepository

        async with SessionFactory() as session:
            deleted = await RefreshTokenRepository(session).purge_expired()
            await session.commit()
            return deleted

    deleted = asyncio.run(_run())
    logger.info("worker.purged_expired_tokens", deleted=deleted)
    return {"deleted": deleted}
