"""Notifications and alert escalation.

Two responsibilities:

* the in-app inbox — list, unread count, mark read — one notification per user;
* alert fan-out — when a crash crosses the configured severity threshold, one
  notification is created per eligible recipient, and optionally an email is
  sent. Fan-out is best-effort: it must never break crash ingestion, so the
  caller wraps it and a failure is logged, not raised.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.audit_log import AuditAction
from app.models.crash import CrashReport
from app.models.device import Device
from app.models.notification import (
    AlertSettings,
    Notification,
    NotificationCategory,
    NotificationLevel,
)
from app.models.user import User
from app.repositories.notification import AlertSettingsRepository, NotificationRepository
from app.repositories.user import UserRepository
from app.schemas.notification import AlertSettingsUpdate
from app.services.audit import AuditService
from app.services.auth import RequestContext
from app.services.email import EmailSender, OutgoingEmail

logger = get_logger(__name__)

#: Total order over severities so a threshold comparison is unambiguous.
SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class NotificationService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        notifications: NotificationRepository,
        alert_settings: AlertSettingsRepository,
        users: UserRepository,
        email_sender: EmailSender,
        audit: AuditService,
        settings: Settings,
    ) -> None:
        self.session = session
        self.notifications = notifications
        self.alert_settings = alert_settings
        self.users = users
        self.email_sender = email_sender
        self.audit = audit
        self.settings = settings

    # ------------------------------------------------------------------
    # Inbox
    # ------------------------------------------------------------------
    async def list_for_user(
        self, user_id: uuid.UUID, *, unread_only: bool, offset: int, limit: int
    ) -> tuple[Sequence[Notification], int]:
        return await self.notifications.list_for_user(
            user_id, unread_only=unread_only, offset=offset, limit=limit
        )

    async def unread_count(self, user_id: uuid.UUID) -> int:
        return await self.notifications.unread_count(user_id)

    async def mark_read(self, notification_id: uuid.UUID, *, user_id: uuid.UUID) -> Notification:
        notification = await self.notifications.get_for_user(notification_id, user_id)
        if notification is None:
            raise NotFoundError("Notification not found.")
        if notification.read_at is None:
            notification.read_at = datetime.now(UTC)
            await self.session.commit()
        return notification

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        count = await self.notifications.mark_all_read(user_id)
        await self.session.commit()
        return count

    # ------------------------------------------------------------------
    # Alert settings
    # ------------------------------------------------------------------
    async def get_settings(self) -> AlertSettings:
        """The stored policy, or a transient default built from config.

        The default is not persisted until an admin saves it, so a fresh install
        behaves per config without a migration data step.
        """
        existing = await self.alert_settings.get_singleton()
        if existing is not None:
            if existing.recipient_roles is None:
                existing.recipient_roles = list(self.settings.ALERT_RECIPIENT_ROLES)
            return existing
        return AlertSettings(
            enabled=self.settings.ALERTS_ENABLED,
            email_enabled=self.settings.ALERT_EMAIL_ENABLED,
            min_severity=self.settings.ALERT_MIN_SEVERITY,
            recipient_roles=list(self.settings.ALERT_RECIPIENT_ROLES),
            notify_on_regression=True,
        )

    async def update_settings(
        self, payload: AlertSettingsUpdate, *, actor: User, ctx: RequestContext | None = None
    ) -> AlertSettings:
        ctx = ctx or RequestContext()
        record = await self.alert_settings.get_singleton()
        if record is None:
            record = await self.get_settings()
            self.session.add(record)

        data = payload.model_dump(exclude_unset=True)
        for field, value in data.items():
            setattr(record, field, value)

        await self.session.flush()
        await self.audit.record(
            AuditAction.ALERT_SETTINGS_UPDATED,
            actor_id=actor.id,
            actor_email=actor.email,
            resource_type="alert_settings",
            resource_id=record.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            context={"changed": list(data.keys())},
        )
        await self.session.commit()
        return record

    # ------------------------------------------------------------------
    # Alert fan-out
    # ------------------------------------------------------------------
    async def alert_for_crash(self, report: CrashReport, device: Device) -> int:
        """Create alert notifications for a crash if it meets the threshold.

        Returns the number of notifications created. Best-effort by contract —
        the caller treats any exception as non-fatal.
        """
        policy = await self.get_settings()
        if not policy.enabled:
            return 0

        threshold = SEVERITY_RANK.get(policy.min_severity, 3)
        if SEVERITY_RANK.get(report.severity, 0) < threshold:
            return 0

        roles = policy.recipient_roles or list(self.settings.ALERT_RECIPIENT_ROLES)
        recipients = await self.users.list_by_roles(roles)
        if not recipients:
            return 0

        level = (
            NotificationLevel.CRITICAL
            if report.severity == "critical"
            else NotificationLevel.WARNING
        )
        where = report.top_function or (
            f"0x{report.program_counter:08X}" if report.program_counter is not None else "unknown"
        )
        title = f"{report.severity.title()} crash on {device.device_id}"
        body = (
            f"A {report.fault_type.replace('_', ' ')} occurred on {device.device_id} "
            f"(firmware {report.firmware_version}) in {where}"
            + (f", task {report.task_name}" if report.task_name else "")
            + "."
        )
        meta = {
            "device_id": device.device_id,
            "fault_type": report.fault_type,
            "severity": report.severity,
        }

        rows = [
            Notification(
                user_id=user.id,
                level=level,
                category=NotificationCategory.CRASH_ALERT,
                title=title,
                body=body,
                resource_type="crash_report",
                resource_id=report.id,
                meta=meta,
            )
            for user in recipients
        ]
        self.notifications.add_all(rows)
        await self.session.commit()

        if policy.email_enabled:
            self._email_recipients(recipients, subject=title, body=body)

        logger.info(
            "alert.crash_escalated",
            crash_id=str(report.id),
            severity=report.severity,
            recipients=len(rows),
            email=policy.email_enabled,
        )
        return len(rows)

    def _email_recipients(
        self, recipients: Sequence[User], *, subject: str, body: str
    ) -> None:
        """Send the alert email to each recipient, best-effort per address."""
        for user in recipients:
            try:
                self.email_sender.send(
                    OutgoingEmail(
                        to=user.email,
                        subject=f"[BlackBox] {subject}",
                        text_body=body,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - one bad address must not stop the rest
                logger.warning("alert.email_failed", to=user.email, error=str(exc))
