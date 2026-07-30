"""Crash group repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, or_, select

from app.models.crash import CrashReport
from app.models.crash_group import CrashGroup
from app.repositories.base import BaseRepository


class CrashGroupRepository(BaseRepository[CrashGroup]):
    model = CrashGroup

    async def get_by_signature(self, signature: str) -> CrashGroup | None:
        stmt = select(CrashGroup).where(CrashGroup.signature == signature).limit(1)
        return (await self.session.execute(stmt)).scalars().first()

    async def search(
        self,
        *,
        query: str | None = None,
        status: str | None = None,
        fault_type: str | None = None,
        severity: str | None = None,
        firmware_version: str | None = None,
        since: datetime | None = None,
        offset: int = 0,
        limit: int = 20,
        sort: str = "-last_seen_at",
    ) -> tuple[Sequence[CrashGroup], int]:
        """Filtered, paginated group listing. Returns ``(items, total)``."""
        conditions = []
        if status:
            conditions.append(CrashGroup.status == status)
        if fault_type:
            conditions.append(CrashGroup.fault_type == fault_type)
        if severity:
            conditions.append(CrashGroup.severity == severity)
        if since:
            conditions.append(CrashGroup.last_seen_at >= since)
        if query:
            pattern = f"%{query.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(CrashGroup.title).like(pattern),
                    func.lower(func.coalesce(CrashGroup.top_function, "")).like(pattern),
                    func.lower(func.coalesce(CrashGroup.task_name, "")).like(pattern),
                    func.lower(func.coalesce(CrashGroup.notes, "")).like(pattern),
                )
            )

        stmt = select(CrashGroup)
        count_stmt = select(func.count(func.distinct(CrashGroup.id))).select_from(CrashGroup)

        # Firmware is stored on the reports, so filtering by it needs the join.
        if firmware_version:
            stmt = stmt.join(CrashGroup.reports).where(
                CrashReport.firmware_version == firmware_version
            )
            count_stmt = count_stmt.join(CrashGroup.reports).where(
                CrashReport.firmware_version == firmware_version
            )
            stmt = stmt.distinct()

        if conditions:
            stmt = stmt.where(*conditions)
            count_stmt = count_stmt.where(*conditions)

        total = int((await self.session.execute(count_stmt)).scalar_one())
        stmt = stmt.order_by(self._order_by(sort)).offset(offset).limit(limit)
        items = (await self.session.execute(stmt)).scalars().unique().all()
        return items, total

    @staticmethod
    def _order_by(sort: str):  # type: ignore[no-untyped-def]
        """Map a ``?sort=`` value onto a column, defaulting to most recent."""
        descending = sort.startswith("-")
        name = sort.lstrip("-") or "last_seen_at"
        allowed = {
            "last_seen_at": CrashGroup.last_seen_at,
            "first_seen_at": CrashGroup.first_seen_at,
            "occurrence_count": CrashGroup.occurrence_count,
            "device_count": CrashGroup.device_count,
            "severity": CrashGroup.severity,
            "title": CrashGroup.title,
        }
        column = allowed.get(name, CrashGroup.last_seen_at)
        return column.desc() if descending else column.asc()

    async def recompute_counters(self, group: CrashGroup) -> None:
        """Recalculate a group's counters from its reports.

        The counters are normally maintained incrementally on ingest. This is
        the repair path — used after reports are deleted or re-grouped, where
        incremental arithmetic would drift.
        """
        stmt = select(
            func.count(CrashReport.id),
            func.count(func.distinct(CrashReport.device_id)),
            func.min(CrashReport.occurred_at),
            func.max(CrashReport.occurred_at),
        ).where(CrashReport.group_id == group.id)
        occurrences, devices, first_seen, last_seen = (await self.session.execute(stmt)).one()

        group.occurrence_count = int(occurrences or 0)
        group.device_count = int(devices or 0)
        if first_seen:
            group.first_seen_at = first_seen
        if last_seen:
            group.last_seen_at = last_seen

        versions = (
            (
                await self.session.execute(
                    select(CrashReport.firmware_version)
                    .where(CrashReport.group_id == group.id)
                    .distinct()
                    .order_by(CrashReport.firmware_version)
                )
            )
            .scalars()
            .all()
        )
        group.affected_firmware_versions = {"versions": [str(v) for v in versions]}
        await self.session.flush()

    async def distinct_device_count(self, group_id: uuid.UUID) -> int:
        stmt = select(func.count(func.distinct(CrashReport.device_id))).where(
            CrashReport.group_id == group_id
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def top_groups(self, *, limit: int = 10) -> list[CrashGroup]:
        """Most frequent open groups — the "most common root causes" tile."""
        stmt = (
            select(CrashGroup)
            .where(CrashGroup.status.in_(["open", "investigating", "regressed"]))
            .order_by(CrashGroup.occurrence_count.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())
