"""Crash report model.

One row per fault reported by a device. Fields fall into four groups:

* **identity** — which device, which firmware/build, when it happened;
* **fault detail** — the ARM Cortex-M fault classification and register state;
* **triage** — severity, workflow status and engineer notes;
* **diagnosis** — AI output, populated in Phase 3.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import GUID, Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.device import Device


class FaultType(StrEnum):
    """Cortex-M fault classification.

    ``UNKNOWN`` is deliberately part of the vocabulary: a report that cannot be
    classified is still worth storing, and discarding it would lose the very
    crashes most in need of diagnosis.
    """

    HARD_FAULT = "hard_fault"
    BUS_FAULT = "bus_fault"
    MEM_MANAGE_FAULT = "mem_manage_fault"
    USAGE_FAULT = "usage_fault"
    STACK_OVERFLOW = "stack_overflow"
    WATCHDOG_RESET = "watchdog_reset"
    ASSERTION_FAILED = "assertion_failed"
    MALLOC_FAILED = "malloc_failed"
    PANIC = "panic"
    UNKNOWN = "unknown"


class CrashSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CrashStatus(StrEnum):
    """Triage workflow state."""

    NEW = "new"
    TRIAGED = "triaged"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    IGNORED = "ignored"
    DUPLICATE = "duplicate"


class CrashReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single crash reported by a device."""

    __tablename__ = "crash_reports"
    __table_args__ = (
        # The dashboard's most common query is "recent crashes for a device",
        # and the analytics views group by fault type over a time window.
        Index("ix_crash_reports_device_id_occurred_at", "device_id", "occurred_at"),
        Index("ix_crash_reports_fault_type_occurred_at", "fault_type", "occurred_at"),
    )

    # -- identity ------------------------------------------------------
    device_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("devices.id", ondelete="CASCADE"), index=True, nullable=False
    )
    firmware_version: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    build_version: Mapped[str | None] = mapped_column(String(100), index=True)
    #: When the fault happened on the device.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    #: When the platform accepted the report. Differs from ``occurred_at`` when
    #: a device buffers reports while offline.
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # -- fault detail --------------------------------------------------
    fault_type: Mapped[str] = mapped_column(
        String(30), default=FaultType.UNKNOWN, index=True, nullable=False
    )
    exception_type: Mapped[str | None] = mapped_column(String(100))
    task_name: Mapped[str | None] = mapped_column(String(100), index=True)
    #: 32-bit addresses stored as BigInteger: a signed 32-bit column cannot
    #: hold addresses above 0x7FFFFFFF.
    program_counter: Mapped[int | None] = mapped_column(BigInteger)
    link_register: Mapped[int | None] = mapped_column(BigInteger)
    stack_pointer: Mapped[int | None] = mapped_column(BigInteger)
    #: {"r0": 0, ..., "psr": 0} — normalised by the crash parser.
    register_dump: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    #: {"start_address": int, "words": [int, ...]}
    stack_dump: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    #: Exactly what the device sent, kept so a report can be re-parsed when the
    #: parser improves or symbolization arrives in a later phase.
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    #: Non-fatal problems found while parsing (unknown fields, odd formats).
    parse_warnings: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    parser_version: Mapped[str | None] = mapped_column(String(20))

    # -- triage --------------------------------------------------------
    severity: Mapped[str] = mapped_column(
        String(20), default=CrashSeverity.MEDIUM, index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default=CrashStatus.NEW, index=True, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)

    # -- diagnosis (Phase 3) -------------------------------------------
    ai_diagnosis: Mapped[str | None] = mapped_column(Text)
    suggested_fix: Mapped[str | None] = mapped_column(Text)
    #: 0.0-1.0. Null means no diagnosis has been attempted yet.
    confidence_score: Mapped[float | None] = mapped_column(Float)
    diagnosed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    device: Mapped[Device] = relationship(back_populates="crash_reports", lazy="selectin")

    @property
    def is_diagnosed(self) -> bool:
        return self.ai_diagnosis is not None

    @property
    def is_open(self) -> bool:
        """True while the crash still needs engineering attention."""
        return self.status in (CrashStatus.NEW, CrashStatus.TRIAGED, CrashStatus.INVESTIGATING)
