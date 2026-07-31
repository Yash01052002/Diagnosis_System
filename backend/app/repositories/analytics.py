"""Read-only aggregation queries for analytics and dashboards.

These span several aggregates, so they live in one analytics-specific repository
rather than being scattered across the per-aggregate repositories. Every query
here is a ``GROUP BY``/``COUNT`` — no rows are written.

Date bucketing is the one place SQL portability bites: SQLite and PostgreSQL
spell "the day part of a timestamp" differently, so ``_day_expr`` picks the
right function for the active dialect. Everything else is standard SQL.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Float, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crash import CrashReport, CrashStatus
from app.models.crash_group import CrashGroup, CrashGroupStatus
from app.models.device import Device, DeviceStatus
from app.models.diagnosis import AiDiagnosis
from app.models.document import Document

#: Crash statuses that count as "still open".
OPEN_STATUSES = (CrashStatus.NEW, CrashStatus.TRIAGED, CrashStatus.INVESTIGATING)


class AnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _day_expr(self) -> Any:
        """A ``YYYY-MM-DD`` text expression for ``occurred_at``, per dialect."""
        dialect = self.session.bind.dialect.name if self.session.bind else "sqlite"
        if dialect == "postgresql":
            return func.to_char(CrashReport.occurred_at, "YYYY-MM-DD")
        # SQLite (tests) and a safe default.
        return func.strftime("%Y-%m-%d", CrashReport.occurred_at)

    async def _scalar(self, stmt: Any) -> int:
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    # ------------------------------------------------------------------
    # Totals
    # ------------------------------------------------------------------
    async def device_totals(self, online_cutoff: datetime) -> tuple[int, int, int]:
        total = await self._scalar(select(func.count()).select_from(Device))
        active = await self._scalar(
            select(func.count()).select_from(Device).where(Device.status == DeviceStatus.ACTIVE)
        )
        online = await self._scalar(
            select(func.count())
            .select_from(Device)
            .where(Device.last_online_at.is_not(None), Device.last_online_at >= online_cutoff)
        )
        return total, active, online

    async def crash_totals(
        self, *, start_of_today: datetime, week_ago: datetime
    ) -> dict[str, int]:
        base = select(func.count()).select_from(CrashReport)
        return {
            "total": await self._scalar(base),
            "today": await self._scalar(base.where(CrashReport.occurred_at >= start_of_today)),
            "last_7d": await self._scalar(base.where(CrashReport.occurred_at >= week_ago)),
            "open": await self._scalar(base.where(CrashReport.status.in_(OPEN_STATUSES))),
            "critical_open": await self._scalar(
                base.where(
                    CrashReport.severity == "critical",
                    CrashReport.status.in_(OPEN_STATUSES),
                )
            ),
        }

    async def devices_with_open_critical(self) -> int:
        stmt = (
            select(func.count(func.distinct(CrashReport.device_id)))
            .where(
                CrashReport.severity == "critical",
                CrashReport.status.in_(OPEN_STATUSES),
            )
        )
        return await self._scalar(stmt)

    async def diagnoses_total(self) -> int:
        return await self._scalar(select(func.count()).select_from(AiDiagnosis))

    async def documents_total(self) -> int:
        return await self._scalar(select(func.count()).select_from(Document))

    # ------------------------------------------------------------------
    # Distributions
    # ------------------------------------------------------------------
    async def _grouped_counts(self, column: Any) -> list[tuple[str, int]]:
        stmt = (
            select(column, func.count().label("n"))
            .group_by(column)
            .order_by(func.count().desc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [(str(key), int(count)) for key, count in rows]

    async def by_fault_type(self) -> list[tuple[str, int]]:
        return await self._grouped_counts(CrashReport.fault_type)

    async def by_severity(self) -> list[tuple[str, int]]:
        return await self._grouped_counts(CrashReport.severity)

    async def by_status(self) -> list[tuple[str, int]]:
        return await self._grouped_counts(CrashReport.status)

    # ------------------------------------------------------------------
    # Top crash groups (root causes)
    # ------------------------------------------------------------------
    async def top_groups(self, limit: int) -> Sequence[CrashGroup]:
        stmt = (
            select(CrashGroup)
            .where(
                CrashGroup.status.in_(
                    (
                        CrashGroupStatus.OPEN,
                        CrashGroupStatus.INVESTIGATING,
                        CrashGroupStatus.REGRESSED,
                    )
                )
            )
            .order_by(CrashGroup.occurrence_count.desc())
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    # ------------------------------------------------------------------
    # Time series
    # ------------------------------------------------------------------
    async def crash_trend(self, since: datetime) -> list[tuple[str, int, int]]:
        day = self._day_expr()
        critical = func.sum(case((CrashReport.severity == "critical", 1), else_=0))
        stmt = (
            select(day.label("day"), func.count().label("n"), critical.label("crit"))
            .where(CrashReport.occurred_at >= since)
            .group_by(day)
            .order_by(day)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(str(d), int(n), int(c or 0)) for d, n, c in rows]

    # ------------------------------------------------------------------
    # Firmware comparison
    # ------------------------------------------------------------------
    async def firmware_stats(self, limit: int) -> list[tuple[str, int, int]]:
        stmt = (
            select(
                CrashReport.firmware_version,
                func.count().label("crashes"),
                func.count(func.distinct(CrashReport.device_id)).label("devices"),
            )
            .group_by(CrashReport.firmware_version)
            .order_by(func.count().desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(str(v), int(c), int(d)) for v, c, d in rows]

    # ------------------------------------------------------------------
    # Device reliability
    # ------------------------------------------------------------------
    async def device_crash_spans(
        self, limit: int
    ) -> list[tuple[uuid.UUID, str, str, int, datetime | None, datetime | None]]:
        """Per device: crash count and first/last crash timestamps."""
        stmt = (
            select(
                Device.id,
                Device.device_id,
                Device.hardware_model,
                func.count(CrashReport.id).label("crashes"),
                func.min(CrashReport.occurred_at).label("first"),
                func.max(CrashReport.occurred_at).label("last"),
            )
            .join(CrashReport, CrashReport.device_id == Device.id)
            .group_by(Device.id, Device.device_id, Device.hardware_model)
            .order_by(func.count(CrashReport.id).desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            (dev_id, str(ident), str(model), int(crashes), first, last)
            for dev_id, ident, model, crashes, first, last in rows
        ]

    async def fleet_crash_span(self) -> tuple[int, datetime | None, datetime | None]:
        stmt = select(
            func.count(CrashReport.id),
            func.min(CrashReport.occurred_at),
            func.max(CrashReport.occurred_at),
        )
        row = (await self.session.execute(stmt)).one()
        return int(row[0] or 0), row[1], row[2]

    # ------------------------------------------------------------------
    # AI confidence distribution
    # ------------------------------------------------------------------
    async def confidence_by_label(self) -> list[tuple[str, int]]:
        return await self._grouped_counts(AiDiagnosis.confidence_label)

    async def confidence_score_buckets(self) -> list[tuple[str, int]]:
        score = AiDiagnosis.confidence_score
        bucket = case(
            (score < 0.2, "0.0-0.2"),
            (score < 0.4, "0.2-0.4"),
            (score < 0.6, "0.4-0.6"),
            (score < 0.8, "0.6-0.8"),
            else_="0.8-1.0",
        )
        stmt = select(bucket.label("bucket"), func.count().label("n")).group_by(bucket)
        rows = (await self.session.execute(stmt)).all()
        return [(str(b), int(n)) for b, n in rows]

    async def confidence_summary(self) -> tuple[int, int, float | None]:
        total = await self._scalar(select(func.count()).select_from(AiDiagnosis))
        uncertain = await self._scalar(
            select(func.count()).select_from(AiDiagnosis).where(AiDiagnosis.is_uncertain.is_(True))
        )
        avg = (
            await self.session.execute(
                select(func.avg(cast(AiDiagnosis.confidence_score, Float)))
            )
        ).scalar_one()
        return total, uncertain, (float(avg) if avg is not None else None)
