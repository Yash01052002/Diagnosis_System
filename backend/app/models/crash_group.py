"""Crash grouping — the same bug, seen many times.

A fleet of a thousand devices hitting one firmware defect produces a thousand
crash reports. Listing them individually buries the fact that it is a single
problem. A :class:`CrashGroup` collects every report sharing a signature, so
the UI can say "seen 847 times across 213 devices since Tuesday" instead.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.crash import CrashReport


class CrashGroupStatus(StrEnum):
    """Triage state of the underlying defect, not of one occurrence."""

    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    IGNORED = "ignored"
    REGRESSED = "regressed"


class CrashGroup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A set of crash reports that share a signature."""

    __tablename__ = "crash_groups"
    __table_args__ = (Index("ix_crash_groups_status_last_seen", "status", "last_seen_at"),)

    #: Stable hash over fault type, task and the top symbolized frames.
    signature: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    #: The inputs that produced the signature, kept so it can be explained.
    signature_components: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    #: Short label, e.g. "hard fault in vTaskDelay".
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    fault_type: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    task_name: Mapped[str | None] = mapped_column(String(100))
    #: Innermost resolved function — where the fault actually happened.
    top_function: Mapped[str | None] = mapped_column(String(255), index=True)

    status: Mapped[str] = mapped_column(
        String(20), default=CrashGroupStatus.OPEN, index=True, nullable=False
    )
    #: Highest severity seen across the group's occurrences.
    severity: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)

    #: Denormalised counters. Recomputing these from crash_reports on every
    #: dashboard load would mean a COUNT DISTINCT over the largest table in
    #: the system; they are maintained transactionally on ingest instead.
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    device_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    #: Firmware versions the group has been observed in, newest first.
    affected_firmware_versions: Mapped[dict[str, Any] | None] = mapped_column(JSONType)

    notes: Mapped[str | None] = mapped_column(Text)
    #: Set when a group marked resolved starts occurring again.
    regressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    reports: Mapped[list[CrashReport]] = relationship(
        back_populates="group",
        lazy="noload",
        passive_deletes=True,
    )

    @property
    def is_open(self) -> bool:
        return self.status in (
            CrashGroupStatus.OPEN,
            CrashGroupStatus.INVESTIGATING,
            CrashGroupStatus.REGRESSED,
        )

    @property
    def firmware_versions(self) -> list[str]:
        payload = self.affected_firmware_versions or {}
        versions = payload.get("versions", [])
        return [str(version) for version in versions]
