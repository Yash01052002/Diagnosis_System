"""Read-only access to the audit trail (admin only)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import PaginationDep, SessionDep, require_admin
from app.repositories.audit_log import AuditLogRepository
from app.schemas.common import BaseSchema, Page

router = APIRouter(prefix="/audit-logs", tags=["Audit"])


class AuditLogRead(BaseSchema):
    id: uuid.UUID
    action: str
    actor_id: uuid.UUID | None = None
    actor_email: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    success: bool
    context: dict[str, Any] | None = None
    created_at: datetime


@router.get(
    "",
    response_model=Page[AuditLogRead],
    dependencies=[Depends(require_admin)],
    summary="Search the audit trail",
)
async def list_audit_logs(
    session: SessionDep,
    pagination: PaginationDep,
    action: Annotated[str | None, Query(description="Exact action name")] = None,
    actor_id: Annotated[uuid.UUID | None, Query(description="Filter by actor")] = None,
    resource_type: Annotated[str | None, Query(description="Filter by resource type")] = None,
    since: Annotated[datetime | None, Query(description="Created at or after")] = None,
    until: Annotated[datetime | None, Query(description="Created at or before")] = None,
) -> Page[AuditLogRead]:
    """Newest-first, paginated view of security events. Requires ``admin``."""
    repository = AuditLogRepository(session)
    items, total = await repository.search(
        action=action,
        actor_id=actor_id,
        resource_type=resource_type,
        since=since,
        until=until,
        offset=pagination.offset,
        limit=pagination.limit,
    )
    return Page.create([AuditLogRead.model_validate(item) for item in items], total, pagination)
