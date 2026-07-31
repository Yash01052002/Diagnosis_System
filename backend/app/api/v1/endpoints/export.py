"""CSV and PDF export endpoints (viewer role)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import AnalyticsServiceDep, CrashServiceDep, CurrentUser, require_viewer
from app.services.export import build_analytics_pdf, build_crashes_csv

router = APIRouter(
    prefix="/export",
    tags=["Export"],
    dependencies=[Depends(require_viewer)],
)

#: Hard cap so a CSV export can never try to stream the entire table into memory.
MAX_EXPORT_ROWS = 10_000


@router.get(
    "/crashes.csv",
    summary="Export crash history as CSV",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
async def export_crashes_csv(
    service: CrashServiceDep,
    device: Annotated[str | None, Query(description="Device identifier or serial")] = None,
    firmware_version: str | None = None,
    fault_type: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    task_name: str | None = None,
    group_id: uuid.UUID | None = None,
) -> Response:
    """The current crash history (filtered like the list view) as a CSV file.

    Capped at the most recent `MAX_EXPORT_ROWS` matching reports so the response
    is bounded; narrow the filters for a targeted export.
    """
    crashes, _total = await service.search(
        device_identifier=device,
        firmware_version=firmware_version,
        fault_type=fault_type,
        severity=severity,
        status=status,
        task_name=task_name,
        group_id=group_id,
        offset=0,
        limit=MAX_EXPORT_ROWS,
        sort="-occurred_at",
    )
    csv_text = build_crashes_csv(crashes)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="crashes-{stamp}.csv"'},
    )


@router.get(
    "/analytics.pdf",
    summary="Export the analytics report as PDF",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def export_analytics_pdf(
    service: AnalyticsServiceDep,
    user: CurrentUser,
) -> Response:
    """A one-page analytics report (overview, fault distribution, top root
    causes, firmware comparison, reliability) as a PDF."""
    summary = await service.dashboard()
    firmware = await service.firmware_comparison(limit=12)
    reliability = await service.device_reliability(limit=10)
    pdf = build_analytics_pdf(
        summary=summary,
        firmware=firmware,
        reliability=reliability,
        generated_by=user.email,
    )
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="analytics-{stamp}.pdf"'},
    )
