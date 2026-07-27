"""Crash report endpoints.

`POST /crashes` is the ingestion path used by firmware in the field; the rest
are the engineering views over the resulting history.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import (
    AdminUser,
    CrashServiceDep,
    EngineerUser,
    IngestPrincipalDep,
    PaginationDep,
    RequestContextDep,
    require_viewer,
)
from app.models.crash import CrashSeverity, CrashStatus, FaultType
from app.schemas.common import ErrorResponse, Page
from app.schemas.crash import (
    CrashAccepted,
    CrashReportListItem,
    CrashReportRead,
    CrashReportSubmit,
    CrashReportUpdate,
)

router = APIRouter(prefix="/crashes", tags=["Crash Reports"])


@router.post(
    "",
    response_model=CrashAccepted,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a crash report",
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid credentials"},
        404: {"model": ErrorResponse, "description": "Device is not registered"},
        422: {"model": ErrorResponse, "description": "Report could not be parsed"},
    },
)
async def submit_crash(
    payload: CrashReportSubmit,
    request: Request,
    principal: IngestPrincipalDep,
    service: CrashServiceDep,
    ctx: RequestContextDep,
) -> CrashAccepted:
    """Ingest a crash report from a device.

    **Authentication** — either a device API key in `X-API-Key` (the firmware
    path), or an engineer bearer token. With a key the device is identified by
    the key itself, so `device_id` in the body is optional and ignored.

    **Parsing** — field names, address formats and timestamps vary between
    firmware builds, so the payload is normalised rather than rejected.
    Non-fatal issues come back in `warnings`; the report is still stored, and
    the original payload is retained for re-parsing.

    **Duplicates** — a report identical to one received moments ago (same
    device, fault type and program counter) returns the existing report
    instead of creating a second row, so a device retrying an upload it never
    saw acknowledged does not distort the counts.
    """
    # The validated model drops unknown keys from typed fields, so the raw body
    # is used: a firmware revision that adds a field must not lose it.
    raw = await request.json()
    result = await service.ingest(
        raw if isinstance(raw, dict) else payload.model_dump(),
        device=principal.device,
        actor=principal.user,
        ctx=ctx,
    )
    return CrashAccepted(
        id=result.report.id,
        status=CrashStatus(result.report.status),
        severity=CrashSeverity(result.report.severity),
        fault_type=FaultType(result.report.fault_type),
        received_at=result.report.received_at,
        warnings=result.warnings,
    )


@router.get(
    "",
    response_model=Page[CrashReportListItem],
    dependencies=[Depends(require_viewer)],
    summary="Search crash history",
)
async def list_crashes(
    service: CrashServiceDep,
    pagination: PaginationDep,
    device_id: Annotated[uuid.UUID | None, Query(description="Internal device id")] = None,
    device: Annotated[str | None, Query(description="Device identifier or serial number")] = None,
    firmware_version: Annotated[str | None, Query(description="Exact firmware version")] = None,
    build_version: Annotated[str | None, Query(description="Exact build version")] = None,
    fault_type: Annotated[FaultType | None, Query(description="Filter by fault type")] = None,
    severity: Annotated[CrashSeverity | None, Query(description="Filter by severity")] = None,
    status_filter: Annotated[
        CrashStatus | None, Query(alias="status", description="Filter by triage status")
    ] = None,
    task_name: Annotated[str | None, Query(description="Exact FreeRTOS task name")] = None,
    occurred_from: Annotated[datetime | None, Query(description="Occurred at or after")] = None,
    occurred_to: Annotated[datetime | None, Query(description="Occurred at or before")] = None,
    diagnosed: Annotated[
        bool | None, Query(description="Only crashes with (or without) an AI diagnosis")
    ] = None,
    q: Annotated[
        str | None, Query(description="Search task, exception, notes or diagnosis")
    ] = None,
    sort: Annotated[
        str,
        Query(
            description=(
                "Sort field, '-' for descending. One of occurred_at, received_at, "
                "severity, fault_type, status, confidence_score."
            )
        ),
    ] = "-occurred_at",
) -> Page[CrashReportListItem]:
    """Paginated crash history with the filters the dashboard needs.

    Register and stack dumps are omitted from list rows; fetch a single report
    to see them.
    """
    items, total = await service.search(
        device_id=device_id,
        device_identifier=device,
        firmware_version=firmware_version,
        build_version=build_version,
        fault_type=fault_type,
        severity=severity,
        status=status_filter,
        task_name=task_name,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        diagnosed=diagnosed,
        query=q,
        sort=sort,
        offset=pagination.offset,
        limit=pagination.limit,
    )
    return Page.create(
        [CrashReportListItem.model_validate(item) for item in items], total, pagination
    )


@router.get(
    "/{crash_id}",
    response_model=CrashReportRead,
    dependencies=[Depends(require_viewer)],
    summary="Get a crash report",
    responses={404: {"model": ErrorResponse, "description": "Crash report not found"}},
)
async def get_crash(crash_id: uuid.UUID, service: CrashServiceDep) -> CrashReportRead:
    """Full crash report including the register and stack dumps."""
    return CrashReportRead.model_validate(await service.get(crash_id))


@router.patch(
    "/{crash_id}",
    response_model=CrashReportRead,
    summary="Triage a crash report",
    responses={404: {"model": ErrorResponse, "description": "Crash report not found"}},
)
async def update_crash(
    crash_id: uuid.UUID,
    payload: CrashReportUpdate,
    engineer: EngineerUser,
    service: CrashServiceDep,
    ctx: RequestContextDep,
) -> CrashReportRead:
    """Update triage fields: status, severity and notes.

    The fault evidence — registers, stack, addresses — is immutable. Crash
    reports are forensic records, and an engineer editing them would destroy
    the only account of what the device actually did.
    """
    report = await service.update(crash_id, payload, actor=engineer, ctx=ctx)
    return CrashReportRead.model_validate(report)


@router.delete(
    "/{crash_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a crash report",
    responses={404: {"model": ErrorResponse, "description": "Crash report not found"}},
)
async def delete_crash(
    crash_id: uuid.UUID,
    admin: AdminUser,
    service: CrashServiceDep,
    ctx: RequestContextDep,
) -> None:
    """Permanently delete a crash report. Requires ``admin``.

    Engineers should mark a report `ignored` or `duplicate` instead; deleting
    removes evidence that analytics and future diagnoses depend on.
    """
    await service.delete(crash_id, actor=admin, ctx=ctx)
