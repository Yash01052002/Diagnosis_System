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
        "mark-stale-devices-inactive": {
            "task": "app.worker.mark_stale_devices_inactive",
            "schedule": crontab(minute="*/15"),
        },
    },
)


def _run_async(coro_factory: Any) -> Any:
    """Drive an async unit of work from a synchronous Celery task."""
    return asyncio.run(coro_factory())


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


@celery_app.task(name="app.worker.mark_stale_devices_inactive")
def mark_stale_devices_inactive(threshold_hours: int = 24) -> dict[str, Any]:
    """Flag devices that have not checked in as ``inactive``.

    Only ``active`` devices are touched: a device deliberately marked
    ``maintenance`` or ``decommissioned`` is silent on purpose, and overwriting
    that would erase an operator's decision.
    """

    async def _run() -> int:
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import or_, update

        from app.db.session import SessionFactory
        from app.models.device import Device, DeviceStatus
        from app.repositories.base import affected_rows

        cutoff = datetime.now(UTC) - timedelta(hours=threshold_hours)
        async with SessionFactory() as session:
            result = await session.execute(
                update(Device)
                .where(
                    Device.status == DeviceStatus.ACTIVE,
                    or_(Device.last_online_at < cutoff, Device.last_online_at.is_(None)),
                )
                .values(status=DeviceStatus.INACTIVE)
            )
            await session.commit()
            return affected_rows(result)

    updated = _run_async(_run)
    logger.info("worker.marked_devices_inactive", updated=updated, hours=threshold_hours)
    return {"updated": updated, "threshold_hours": threshold_hours}


@celery_app.task(name="app.worker.reparse_crash_report")
def reparse_crash_report(crash_id: str) -> dict[str, Any]:
    """Re-run the parser over a stored report's original payload.

    This is why ``raw_payload`` is kept: when the parser learns to understand a
    new firmware dialect, existing reports can be upgraded in place rather than
    staying frozen at the quality of whatever shipped first. It is also the
    hook Phase 2.5 extends to attach symbolization.
    """

    async def _run() -> dict[str, Any]:
        import uuid as _uuid

        from app.db.session import SessionFactory
        from app.repositories.crash import CrashReportRepository
        from app.services.crash_parser import crash_parser

        async with SessionFactory() as session:
            repository = CrashReportRepository(session)
            report = await repository.get(_uuid.UUID(crash_id))
            if report is None:
                return {"status": "not_found", "crash_id": crash_id}
            if not report.raw_payload:
                return {"status": "no_raw_payload", "crash_id": crash_id}

            parsed = crash_parser.parse(report.raw_payload)
            report.fault_type = parsed.fault_type
            report.exception_type = parsed.exception_type
            report.task_name = parsed.task_name
            report.program_counter = parsed.program_counter
            report.link_register = parsed.link_register
            report.stack_pointer = parsed.stack_pointer
            report.register_dump = parsed.register_dump
            report.stack_dump = parsed.stack_dump
            report.parse_warnings = {"warnings": parsed.warnings} if parsed.warnings else None
            report.parser_version = parsed.parser_version
            # Severity and status are left alone: an engineer may have triaged
            # this report, and re-parsing must not undo human judgement.
            await session.commit()
            return {
                "status": "reparsed",
                "crash_id": crash_id,
                "parser_version": parsed.parser_version,
                "warnings": len(parsed.warnings),
            }

    result = _run_async(_run)
    logger.info("worker.reparsed_crash", **result)
    return result
