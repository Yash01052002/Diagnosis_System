"""Persistence for notifications and the alert configuration."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select, update

from app.models.notification import AlertSettings, Notification
from app.repositories.base import BaseRepository, affected_rows


class NotificationRepository(BaseRepository[Notification]):
    model = Notification

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        unread_only: bool = False,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[Notification], int]:
        stmt = select(Notification).where(Notification.user_id == user_id)
        count_stmt = (
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id)
        )
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
            count_stmt = count_stmt.where(Notification.read_at.is_(None))

        total = int((await self.session.execute(count_stmt)).scalar_one())
        stmt = stmt.order_by(Notification.created_at.desc()).offset(offset).limit(limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total

    async def unread_count(self, user_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def get_for_user(
        self, notification_id: uuid.UUID, user_id: uuid.UUID
    ) -> Notification | None:
        stmt = select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user_id
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        result = await self.session.execute(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            .values(read_at=datetime.now(UTC))
        )
        return affected_rows(result)

    def add_all(self, notifications: Sequence[Notification]) -> None:
        self.session.add_all(list(notifications))


class AlertSettingsRepository(BaseRepository[AlertSettings]):
    model = AlertSettings

    async def get_singleton(self) -> AlertSettings | None:
        """The one settings row, if it has been created."""
        stmt = select(AlertSettings).order_by(AlertSettings.created_at.asc()).limit(1)
        return (await self.session.execute(stmt)).scalars().first()
