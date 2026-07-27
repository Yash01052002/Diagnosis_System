"""Audit-logging service."""

from __future__ import annotations

import uuid
from typing import Any

from app.models.audit_log import AuditAction, AuditLog
from app.repositories.audit_log import AuditLogRepository


class AuditService:
    """Records security-relevant events.

    Writes are staged on the caller's session so an audit entry is committed in
    the same transaction as the action it describes — an event is never
    recorded for work that was rolled back.
    """

    def __init__(self, repository: AuditLogRepository) -> None:
        self.repository = repository

    async def record(
        self,
        action: AuditAction | str,
        *,
        actor_id: uuid.UUID | None = None,
        actor_email: str | None = None,
        resource_type: str | None = None,
        resource_id: str | uuid.UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        success: bool = True,
        context: dict[str, Any] | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            action=str(action),
            actor_id=actor_id,
            actor_email=actor_email,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            ip_address=ip_address,
            user_agent=user_agent[:255] if user_agent else None,
            success=success,
            context=context,
        )
        self.repository.add(entry)
        return entry
