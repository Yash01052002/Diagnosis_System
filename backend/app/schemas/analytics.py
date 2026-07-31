"""Analytics and dashboard response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.models.crash import CrashSeverity, FaultType
from app.models.crash_group import CrashGroupStatus
from app.schemas.common import BaseSchema


class CountItem(BaseSchema):
    """A labelled count, used for every distribution chart."""

    key: str
    count: int


class DeviceTotals(BaseSchema):
    total: int
    active: int
    #: Checked in within the online window (see ``ANALYTICS_ONLINE_WINDOW_MINUTES``).
    online: int


class CrashTotals(BaseSchema):
    total: int
    today: int
    last_7d: int
    #: Reports still needing attention (new / triaged / investigating).
    open: int
    #: Open reports at ``critical`` severity — the ones that should page someone.
    critical_open: int


class RootCause(BaseSchema):
    """A top crash group, i.e. one distinct bug ranked by frequency."""

    id: uuid.UUID
    title: str
    fault_type: FaultType
    severity: CrashSeverity
    status: CrashGroupStatus
    occurrence_count: int
    device_count: int
    top_function: str | None = None


class DashboardSummary(BaseSchema):
    """Everything the dashboard landing view needs in one round-trip."""

    devices: DeviceTotals
    crashes: CrashTotals
    diagnoses_total: int
    documents_total: int
    #: 0-100. The share of devices with no open critical crash, rounded.
    device_health_score: int
    by_fault_type: list[CountItem]
    by_severity: list[CountItem]
    top_root_causes: list[RootCause]
    generated_at: datetime


class TrendPoint(BaseSchema):
    date: str = Field(examples=["2026-07-30"])
    count: int
    critical: int


class CrashTrend(BaseSchema):
    days: int
    points: list[TrendPoint]
    total: int


class FaultDistribution(BaseSchema):
    by_fault_type: list[CountItem]
    by_severity: list[CountItem]
    by_status: list[CountItem]
    total: int


class FirmwareStat(BaseSchema):
    firmware_version: str
    crashes: int
    devices: int


class FirmwareComparison(BaseSchema):
    firmwares: list[FirmwareStat]


class DeviceReliability(BaseSchema):
    device_id: uuid.UUID
    device_identifier: str
    hardware_model: str
    crashes: int
    last_crash_at: datetime | None = None
    #: Mean time between failures, in hours. Null when a device has < 2 crashes,
    #: because a single crash gives no interval to average.
    mtbf_hours: float | None = None


class DeviceReliabilityReport(BaseSchema):
    #: Fleet-wide mean time between failures, in hours (observation span over
    #: total crashes). Null when there are too few crashes to be meaningful.
    fleet_mtbf_hours: float | None = None
    devices: list[DeviceReliability]


class ConfidenceDistribution(BaseSchema):
    by_label: list[CountItem]
    #: Histogram of confidence scores in fixed 0.2-wide buckets.
    by_score_bucket: list[CountItem]
    total: int
    uncertain: int
    average_score: float | None = None
