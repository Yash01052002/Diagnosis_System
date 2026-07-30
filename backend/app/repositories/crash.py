"""Crash report repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.models.crash import CrashReport, CrashStatus
from app.models.device import Device
from app.repositories.base import BaseRepository

#: Statuses that still need engineering attention.
OPEN_STATUSES = (CrashStatus.NEW, CrashStatus.TRIAGED, CrashStatus.INVESTIGATING)


class CrashReportRepository(BaseRepository[CrashReport]):
    model = CrashReport

    _EAGER = (
        selectinload(CrashReport.device).selectinload(Device.tags),
        selectinload(CrashReport.group),
    )

    async def get_full(self, crash_id: uuid.UUID) -> CrashReport | None:
        stmt = select(CrashReport).where(CrashReport.id == crash_id).options(*self._EAGER)
        return (await self.session.execute(stmt)).scalars().first()

    async def search(
        self,
        *,
        device_id: uuid.UUID | None = None,
        device_identifier: str | None = None,
        group_id: uuid.UUID | None = None,
        firmware_version: str | None = None,
        build_version: str | None = None,
        fault_type: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        task_name: str | None = None,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
        query: str | None = None,
        diagnosed: bool | None = None,
        symbolicated: bool | None = None,
        offset: int = 0,
        limit: int = 20,
        sort: str = "-occurred_at",
    ) -> tuple[Sequence[CrashReport], int]:
        """Filtered, paginated crash history. Returns ``(items, total)``."""
        conditions = []

        if device_id:
            conditions.append(CrashReport.device_id == device_id)
        if group_id:
            conditions.append(CrashReport.group_id == group_id)
        if firmware_version:
            conditions.append(CrashReport.firmware_version == firmware_version)
        if build_version:
            conditions.append(CrashReport.build_version == build_version)
        if fault_type:
            conditions.append(CrashReport.fault_type == fault_type)
        if severity:
            conditions.append(CrashReport.severity == severity)
        if status:
            conditions.append(CrashReport.status == status)
        if task_name:
            conditions.append(func.lower(CrashReport.task_name) == task_name.strip().lower())
        if occurred_from:
            conditions.append(CrashReport.occurred_at >= occurred_from)
        if occurred_to:
            conditions.append(CrashReport.occurred_at <= occurred_to)
        if symbolicated is not None:
            conditions.append(
                CrashReport.symbolicated_at.isnot(None)
                if symbolicated
                else CrashReport.symbolicated_at.is_(None)
            )
        if diagnosed is not None:
            conditions.append(
                CrashReport.ai_diagnosis.isnot(None)
                if diagnosed
                else CrashReport.ai_diagnosis.is_(None)
            )
        if query:
            pattern = f"%{query.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(func.coalesce(CrashReport.task_name, "")).like(pattern),
                    func.lower(func.coalesce(CrashReport.exception_type, "")).like(pattern),
                    func.lower(func.coalesce(CrashReport.notes, "")).like(pattern),
                    func.lower(func.coalesce(CrashReport.ai_diagnosis, "")).like(pattern),
                    func.lower(func.coalesce(CrashReport.top_function, "")).like(pattern),
                )
            )

        stmt = select(CrashReport).options(*self._EAGER)
        count_stmt = select(func.count(func.distinct(CrashReport.id))).select_from(CrashReport)

        # Filtering by the human-facing device identifier requires the join.
        if device_identifier:
            cleaned = device_identifier.strip()
            device_condition = or_(Device.device_id == cleaned, Device.serial_number == cleaned)
            stmt = stmt.join(CrashReport.device).where(device_condition)
            count_stmt = count_stmt.join(CrashReport.device).where(device_condition)

        if conditions:
            stmt = stmt.where(*conditions)
            count_stmt = count_stmt.where(*conditions)

        total = int((await self.session.execute(count_stmt)).scalar_one())
        stmt = stmt.order_by(self._order_by(sort)).offset(offset).limit(limit)
        items = (await self.session.execute(stmt)).scalars().unique().all()
        return items, total

    @staticmethod
    def _order_by(sort: str):  # type: ignore[no-untyped-def]
        """Map a ``?sort=`` value onto a column, defaulting to newest first."""
        descending = sort.startswith("-")
        name = sort.lstrip("-") or "occurred_at"
        allowed = {
            "occurred_at": CrashReport.occurred_at,
            "received_at": CrashReport.received_at,
            "severity": CrashReport.severity,
            "fault_type": CrashReport.fault_type,
            "status": CrashReport.status,
            "confidence_score": CrashReport.confidence_score,
            "top_function": CrashReport.top_function,
        }
        column = allowed.get(name, CrashReport.occurred_at)
        return column.desc() if descending else column.asc()

    # ------------------------------------------------------------------
    # Aggregates (consumed by the Phase 5 dashboard)
    # ------------------------------------------------------------------
    async def count_for_device(self, device_id: uuid.UUID) -> dict[str, int]:
        total = int(
            (
                await self.session.execute(
                    select(func.count())
                    .select_from(CrashReport)
                    .where(CrashReport.device_id == device_id)
                )
            ).scalar_one()
        )
        open_count = int(
            (
                await self.session.execute(
                    select(func.count())
                    .select_from(CrashReport)
                    .where(
                        CrashReport.device_id == device_id,
                        CrashReport.status.in_([s.value for s in OPEN_STATUSES]),
                    )
                )
            ).scalar_one()
        )
        cutoff = datetime.now(UTC) - timedelta(hours=24)
        recent = int(
            (
                await self.session.execute(
                    select(func.count())
                    .select_from(CrashReport)
                    .where(
                        CrashReport.device_id == device_id,
                        CrashReport.occurred_at >= cutoff,
                    )
                )
            ).scalar_one()
        )
        return {"total": total, "open": open_count, "last_24h": recent}

    async def last_crash_at(self, device_id: uuid.UUID) -> datetime | None:
        stmt = select(func.max(CrashReport.occurred_at)).where(CrashReport.device_id == device_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def count_by_fault_type(self, *, since: datetime | None = None) -> dict[str, int]:
        stmt = select(CrashReport.fault_type, func.count()).group_by(CrashReport.fault_type)
        if since:
            stmt = stmt.where(CrashReport.occurred_at >= since)
        rows = (await self.session.execute(stmt)).all()
        return {str(fault_type): int(count) for fault_type, count in rows}

    async def count_since(self, since: datetime) -> int:
        stmt = select(func.count()).select_from(CrashReport).where(CrashReport.occurred_at >= since)
        return int((await self.session.execute(stmt)).scalar_one())

    async def find_recent_duplicate(
        self,
        *,
        device_id: uuid.UUID,
        fault_type: str,
        program_counter: int | None,
        occurred_at: datetime,
        window: timedelta = timedelta(seconds=60),
    ) -> CrashReport | None:
        """Find an identical report already stored within ``window``.

        A device that reboots into the same fault, or retries an upload it
        never saw acknowledged, would otherwise create duplicate rows. This is
        exact-match only; signature-based grouping arrives in Phase 2.5.
        """
        stmt = (
            select(CrashReport)
            .where(
                CrashReport.device_id == device_id,
                CrashReport.fault_type == fault_type,
                CrashReport.occurred_at >= occurred_at - window,
                CrashReport.occurred_at <= occurred_at + window,
                (
                    CrashReport.program_counter == program_counter
                    if program_counter is not None
                    else CrashReport.program_counter.is_(None)
                ),
            )
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()
