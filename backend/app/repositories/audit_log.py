"""Audit-log repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select

from app.models.audit_log import AuditLog
from app.repositories.base import BaseRepository


class AuditLogRepository(BaseRepository[AuditLog]):
    model = AuditLog

    async def search(
        self,
        *,
        action: str | None = None,
        actor_id: uuid.UUID | None = None,
        resource_type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[AuditLog], int]:
        """Filtered, paginated audit trail. Returns ``(items, total)``."""
        conditions = []
        if action:
            conditions.append(AuditLog.action == action)
        if actor_id:
            conditions.append(AuditLog.actor_id == actor_id)
        if resource_type:
            conditions.append(AuditLog.resource_type == resource_type)
        if since:
            conditions.append(AuditLog.created_at >= since)
        if until:
            conditions.append(AuditLog.created_at <= until)

        count_stmt = select(func.count()).select_from(AuditLog)
        stmt = select(AuditLog)
        if conditions:
            count_stmt = count_stmt.where(*conditions)
            stmt = stmt.where(*conditions)

        total = int((await self.session.execute(count_stmt)).scalar_one())
        stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total
