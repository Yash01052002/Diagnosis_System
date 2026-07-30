"""Crash group endpoints — one row per distinct bug."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    CrashServiceDep,
    EngineerUser,
    PaginationDep,
    RequestContextDep,
    SessionDep,
    require_viewer,
)
from app.core.exceptions import NotFoundError, ValidationError
from app.models.audit_log import AuditAction
from app.models.crash import CrashSeverity, FaultType
from app.models.crash_group import CrashGroupStatus
from app.repositories.audit_log import AuditLogRepository
from app.repositories.crash_group import CrashGroupRepository
from app.schemas.build import CrashGroupRead, CrashGroupUpdate
from app.schemas.common import ErrorResponse, Page
from app.schemas.crash import CrashReportListItem
from app.services.audit import AuditService

router = APIRouter(prefix="/crash-groups", tags=["Crash Groups"])


@router.get(
    "",
    response_model=Page[CrashGroupRead],
    dependencies=[Depends(require_viewer)],
    summary="List crash groups",
)
async def list_groups(
    session: SessionDep,
    pagination: PaginationDep,
    q: Annotated[str | None, Query(description="Search title, function, task or notes")] = None,
    status_filter: Annotated[
        CrashGroupStatus | None, Query(alias="status", description="Filter by group status")
    ] = None,
    fault_type: Annotated[FaultType | None, Query(description="Filter by fault type")] = None,
    severity: Annotated[CrashSeverity | None, Query(description="Filter by severity")] = None,
    firmware_version: Annotated[
        str | None, Query(description="Groups seen in this firmware version")
    ] = None,
    since: Annotated[datetime | None, Query(description="Last seen at or after")] = None,
    sort: Annotated[
        str,
        Query(
            description=(
                "Sort field, '-' for descending. One of last_seen_at, first_seen_at, "
                "occurrence_count, device_count, severity, title."
            )
        ),
    ] = "-last_seen_at",
) -> Page[CrashGroupRead]:
    """Distinct bugs rather than individual crashes.

    A fleet hitting one firmware defect produces thousands of reports; this
    collapses them into one row carrying how often and how widely it occurs.
    """
    repository = CrashGroupRepository(session)
    items, total = await repository.search(
        query=q,
        status=status_filter,
        fault_type=fault_type,
        severity=severity,
        firmware_version=firmware_version,
        since=since,
        offset=pagination.offset,
        limit=pagination.limit,
        sort=sort,
    )
    return Page.create([CrashGroupRead.model_validate(item) for item in items], total, pagination)


@router.get(
    "/top",
    response_model=list[CrashGroupRead],
    dependencies=[Depends(require_viewer)],
    summary="Most frequent open groups",
)
async def top_groups(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=50, description="How many to return")] = 10,
) -> list[CrashGroupRead]:
    """The "most common root causes" list, ranked by occurrence count."""
    repository = CrashGroupRepository(session)
    groups = await repository.top_groups(limit=limit)
    return [CrashGroupRead.model_validate(group) for group in groups]


@router.get(
    "/{group_id}",
    response_model=CrashGroupRead,
    dependencies=[Depends(require_viewer)],
    summary="Get a crash group",
    responses={404: {"model": ErrorResponse, "description": "Group not found"}},
)
async def get_group(group_id: uuid.UUID, session: SessionDep) -> CrashGroupRead:
    """One group, including the components its signature was built from."""
    group = await CrashGroupRepository(session).get(group_id)
    if group is None:
        raise NotFoundError("Crash group not found.")
    return CrashGroupRead.model_validate(group)


@router.get(
    "/{group_id}/crashes",
    response_model=Page[CrashReportListItem],
    dependencies=[Depends(require_viewer)],
    summary="Crashes in a group",
)
async def list_group_crashes(
    group_id: uuid.UUID,
    session: SessionDep,
    service: CrashServiceDep,
    pagination: PaginationDep,
) -> Page[CrashReportListItem]:
    """Individual occurrences of one bug, newest first."""
    group = await CrashGroupRepository(session).get(group_id)
    if group is None:
        raise NotFoundError("Crash group not found.")

    items, total = await service.search(
        group_id=group_id, offset=pagination.offset, limit=pagination.limit
    )
    return Page.create(
        [CrashReportListItem.model_validate(item) for item in items], total, pagination
    )


@router.patch(
    "/{group_id}",
    response_model=CrashGroupRead,
    summary="Triage a crash group",
    responses={404: {"model": ErrorResponse, "description": "Group not found"}},
)
async def update_group(
    group_id: uuid.UUID,
    payload: CrashGroupUpdate,
    engineer: EngineerUser,
    session: SessionDep,
    ctx: RequestContextDep,
) -> CrashGroupRead:
    """Set the status or notes of the underlying defect.

    Marking a group `resolved` is a claim about the *bug*, not one crash. If a
    report matching the signature arrives afterwards, the group is
    automatically flipped to `regressed` — a fix that did not hold is more
    urgent than a bug nobody has looked at yet.
    """
    repository = CrashGroupRepository(session)
    group = await repository.get(group_id)
    if group is None:
        raise NotFoundError("Crash group not found.")

    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise ValidationError("No changes supplied.")

    changed: dict[str, object] = {}
    if "status" in data and data["status"] is not None:
        group.status = str(data["status"])
        changed["status"] = group.status
        if group.status != CrashGroupStatus.REGRESSED:
            group.regressed_at = None
    if "notes" in data:
        group.notes = data["notes"]
        changed["notes"] = "updated"

    audit = AuditService(AuditLogRepository(session))
    await audit.record(
        AuditAction.CRASH_GROUP_UPDATED,
        actor_id=engineer.id,
        actor_email=engineer.email,
        resource_type="crash_group",
        resource_id=group.id,
        ip_address=ctx.ip_address,
        user_agent=ctx.user_agent,
        context={"signature": group.signature, **changed},
    )
    await session.commit()
    await session.refresh(group)
    return CrashGroupRead.model_validate(group)
