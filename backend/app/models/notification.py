"""In-app notifications and the alert configuration.

A :class:`Notification` is one message addressed to one user. Alerts (e.g. a
critical crash) fan out to one notification per eligible recipient, so each user
has their own read state. :class:`AlertSettings` is a single-row table holding
the fleet-wide alert policy an admin can tune.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import GUID, Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class NotificationLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class NotificationCategory(StrEnum):
    CRASH_ALERT = "crash_alert"
    REGRESSION = "regression"
    SYSTEM = "system"


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One message to one user, with its own read state."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_read", "user_id", "read_at"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    level: Mapped[str] = mapped_column(
        String(20), default=NotificationLevel.INFO, nullable=False
    )
    category: Mapped[str] = mapped_column(
        String(40), default=NotificationCategory.SYSTEM, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    #: What the notification points at, so the UI can deep-link to it.
    resource_type: Mapped[str | None] = mapped_column(String(50))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    #: Null until the user reads it; indexed so unread counts are cheap.
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONType)

    user: Mapped[User] = relationship(lazy="noload")

    @property
    def is_read(self) -> bool:
        return self.read_at is not None


class AlertSettings(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Fleet-wide alert policy. A single row; defaults come from config.

    Kept in the database (not just config) so an admin can change the policy at
    runtime without a redeploy.
    """

    __tablename__ = "alert_settings"

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Minimum crash severity that raises an alert.
    min_severity: Mapped[str] = mapped_column(String(20), default="critical", nullable=False)
    #: Roles whose users receive alerts.
    recipient_roles: Mapped[list[str] | None] = mapped_column(JSONType)
    #: Also alert when a resolved bug regresses.
    notify_on_regression: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
