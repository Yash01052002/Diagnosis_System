"""Notification and alert-settings schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.models.crash import CrashSeverity
from app.models.notification import NotificationLevel
from app.schemas.common import BaseSchema


class NotificationRead(BaseSchema):
    id: uuid.UUID
    level: NotificationLevel
    category: str
    title: str
    body: str
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None
    read_at: datetime | None = None
    meta: dict[str, Any] | None = None
    created_at: datetime


class UnreadCount(BaseSchema):
    count: int


class AlertSettingsRead(BaseSchema):
    enabled: bool
    email_enabled: bool
    min_severity: CrashSeverity
    recipient_roles: list[str]
    notify_on_regression: bool


class AlertSettingsUpdate(BaseSchema):
    """Partial update of the fleet alert policy."""

    enabled: bool | None = None
    email_enabled: bool | None = None
    min_severity: CrashSeverity | None = None
    recipient_roles: list[str] | None = Field(default=None, max_length=10)
    notify_on_regression: bool | None = None
