"""Analytics: dashboard summary, trends and reliability metrics.

The repository returns raw aggregates; this service turns them into the derived
figures a dashboard shows — a health score, gap-filled time series, and
mean-time-between-failures — so those definitions live in exactly one place.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.repositories.analytics import AnalyticsRepository
from app.schemas.analytics import (
    ConfidenceDistribution,
    CountItem,
    CrashTotals,
    CrashTrend,
    DashboardSummary,
    DeviceReliability,
    DeviceReliabilityReport,
    DeviceTotals,
    FaultDistribution,
    FirmwareComparison,
    FirmwareStat,
    RootCause,
    TrendPoint,
)


def _mtbf_hours(count: int, first: datetime | None, last: datetime | None) -> float | None:
    """Mean time between failures, in hours.

    With N crashes there are N-1 intervals between them, so a single crash gives
    nothing to average and returns ``None``.
    """
    if count < 2 or first is None or last is None:
        return None
    span_hours = (last - first).total_seconds() / 3600
    return round(span_hours / (count - 1), 2)


class AnalyticsService:
    def __init__(self, *, analytics: AnalyticsRepository, settings: Settings) -> None:
        self.analytics = analytics
        self.settings = settings

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    async def dashboard(self) -> DashboardSummary:
        now = datetime.now(UTC)
        online_cutoff = now - timedelta(minutes=self.settings.ANALYTICS_ONLINE_WINDOW_MINUTES)
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = now - timedelta(days=7)

        total_devices, active, online = await self.analytics.device_totals(online_cutoff)
        crash_totals = await self.analytics.crash_totals(
            start_of_today=start_of_today, week_ago=week_ago
        )
        with_critical = await self.analytics.devices_with_open_critical()

        health = 100
        if total_devices:
            health = round(100 * (total_devices - with_critical) / total_devices)

        groups = await self.analytics.top_groups(self.settings.ANALYTICS_TOP_LIMIT)

        return DashboardSummary(
            devices=DeviceTotals(total=total_devices, active=active, online=online),
            crashes=CrashTotals(**crash_totals),
            diagnoses_total=await self.analytics.diagnoses_total(),
            documents_total=await self.analytics.documents_total(),
            device_health_score=health,
            by_fault_type=[
                CountItem(key=k, count=c) for k, c in await self.analytics.by_fault_type()
            ],
            by_severity=[
                CountItem(key=k, count=c) for k, c in await self.analytics.by_severity()
            ],
            top_root_causes=[
                RootCause(
                    id=g.id,
                    title=g.title,
                    fault_type=g.fault_type,
                    severity=g.severity,
                    status=g.status,
                    occurrence_count=g.occurrence_count,
                    device_count=g.device_count,
                    top_function=g.top_function,
                )
                for g in groups
            ],
            generated_at=now,
        )

    # ------------------------------------------------------------------
    # Trends & distributions
    # ------------------------------------------------------------------
    async def crash_trend(self, days: int) -> CrashTrend:
        days = max(1, min(days, 365))
        now = datetime.now(UTC)
        since = (now - timedelta(days=days - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        rows = await self.analytics.crash_trend(since)
        counts = {day: (n, crit) for day, n, crit in rows}

        # Fill every day in the window so the chart has no gaps.
        points: list[TrendPoint] = []
        total = 0
        for offset in range(days):
            day = (since + timedelta(days=offset)).strftime("%Y-%m-%d")
            n, crit = counts.get(day, (0, 0))
            total += n
            points.append(TrendPoint(date=day, count=n, critical=crit))
        return CrashTrend(days=days, points=points, total=total)

    async def fault_distribution(self) -> FaultDistribution:
        fault = await self.analytics.by_fault_type()
        return FaultDistribution(
            by_fault_type=[CountItem(key=k, count=c) for k, c in fault],
            by_severity=[
                CountItem(key=k, count=c) for k, c in await self.analytics.by_severity()
            ],
            by_status=[CountItem(key=k, count=c) for k, c in await self.analytics.by_status()],
            total=sum(c for _, c in fault),
        )

    async def firmware_comparison(self, limit: int) -> FirmwareComparison:
        limit = max(1, min(limit, 50))
        rows = await self.analytics.firmware_stats(limit)
        return FirmwareComparison(
            firmwares=[
                FirmwareStat(firmware_version=v, crashes=c, devices=d) for v, c, d in rows
            ]
        )

    async def device_reliability(self, limit: int) -> DeviceReliabilityReport:
        limit = max(1, min(limit, 100))
        rows = await self.analytics.device_crash_spans(limit)
        devices = [
            DeviceReliability(
                device_id=dev_id,
                device_identifier=ident,
                hardware_model=model,
                crashes=crashes,
                last_crash_at=last,
                mtbf_hours=_mtbf_hours(crashes, first, last),
            )
            for dev_id, ident, model, crashes, first, last in rows
        ]
        total, first, last = await self.analytics.fleet_crash_span()
        return DeviceReliabilityReport(
            fleet_mtbf_hours=_mtbf_hours(total, first, last),
            devices=devices,
        )

    async def confidence_distribution(self) -> ConfidenceDistribution:
        total, uncertain, average = await self.analytics.confidence_summary()
        return ConfidenceDistribution(
            by_label=[
                CountItem(key=k, count=c) for k, c in await self.analytics.confidence_by_label()
            ],
            by_score_bucket=[
                CountItem(key=k, count=c)
                for k, c in await self.analytics.confidence_score_buckets()
            ],
            total=total,
            uncertain=uncertain,
            average_score=round(average, 4) if average is not None else None,
        )
