"""Analytics and dashboard endpoints (read-only, viewer role)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import AnalyticsServiceDep, SettingsDep, require_viewer
from app.schemas.analytics import (
    ConfidenceDistribution,
    CrashTrend,
    DashboardSummary,
    DeviceReliabilityReport,
    FaultDistribution,
    FirmwareComparison,
)

router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"],
    dependencies=[Depends(require_viewer)],
)


@router.get("/summary", response_model=DashboardSummary, summary="Dashboard summary")
async def dashboard_summary(service: AnalyticsServiceDep) -> DashboardSummary:
    """Everything the dashboard landing view needs: device and crash totals, a
    device health score, fault/severity distributions and the top bugs."""
    return await service.dashboard()


@router.get("/crash-trend", response_model=CrashTrend, summary="Crashes over time")
async def crash_trend(
    service: AnalyticsServiceDep,
    settings: SettingsDep,
    days: Annotated[int | None, Query(ge=1, le=365, description="Window in days")] = None,
) -> CrashTrend:
    """Daily crash counts (with a critical-severity split) over the window,
    gap-filled so every day in range is present."""
    return await service.crash_trend(days or settings.ANALYTICS_TREND_DAYS)


@router.get(
    "/fault-distribution", response_model=FaultDistribution, summary="Fault distribution"
)
async def fault_distribution(service: AnalyticsServiceDep) -> FaultDistribution:
    """Crash counts grouped by fault type, severity and triage status."""
    return await service.fault_distribution()


@router.get(
    "/firmware-comparison", response_model=FirmwareComparison, summary="Crashes by firmware"
)
async def firmware_comparison(
    service: AnalyticsServiceDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> FirmwareComparison:
    """Crash counts and affected-device counts per firmware version."""
    return await service.firmware_comparison(limit)


@router.get(
    "/device-reliability", response_model=DeviceReliabilityReport, summary="Device reliability"
)
async def device_reliability(
    service: AnalyticsServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> DeviceReliabilityReport:
    """Per-device crash counts and mean-time-between-failures, plus a
    fleet-wide MTBF."""
    return await service.device_reliability(limit)


@router.get(
    "/confidence-distribution",
    response_model=ConfidenceDistribution,
    summary="AI diagnosis confidence",
)
async def confidence_distribution(service: AnalyticsServiceDep) -> ConfidenceDistribution:
    """How AI diagnoses are distributed across confidence labels and score
    buckets — a read on how well-grounded the knowledge base makes them."""
    return await service.confidence_distribution()
