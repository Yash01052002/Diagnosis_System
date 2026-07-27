"""Append-only audit trail for security-relevant events."""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import GUID, Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin


class AuditAction(StrEnum):
    """Canonical action names recorded in the audit log."""

    USER_REGISTERED = "user.registered"
    USER_LOGIN = "user.login"
    USER_LOGIN_FAILED = "user.login_failed"
    USER_LOGOUT = "user.logout"
    USER_LOCKED = "user.locked"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"
    USER_ROLES_CHANGED = "user.roles_changed"
    TOKEN_REFRESHED = "auth.token_refreshed"
    PASSWORD_RESET_REQUESTED = "auth.password_reset_requested"
    PASSWORD_RESET_COMPLETED = "auth.password_reset_completed"
    PASSWORD_CHANGED = "auth.password_changed"

    DEVICE_CREATED = "device.created"
    DEVICE_UPDATED = "device.updated"
    DEVICE_DELETED = "device.deleted"
    DEVICE_KEY_CREATED = "device.key_created"
    DEVICE_KEY_REVOKED = "device.key_revoked"
    DEVICE_KEY_REJECTED = "device.key_rejected"

    CRASH_RECEIVED = "crash.received"
    CRASH_REJECTED = "crash.rejected"
    CRASH_UPDATED = "crash.updated"
    CRASH_DELETED = "crash.deleted"


class AuditLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per security-relevant event.

    Rows are never updated or deleted by the application; the table is the
    system of record for "who did what, when".
    """

    __tablename__ = "audit_logs"

    action: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    #: Nullable: failed logins for unknown emails have no user.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    actor_email: Mapped[str | None] = mapped_column(String(320), index=True)
    #: Type + id of the object acted upon, e.g. ("user", <uuid>).
    resource_type: Mapped[str | None] = mapped_column(String(50), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    success: Mapped[bool] = mapped_column(default=True, nullable=False)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
