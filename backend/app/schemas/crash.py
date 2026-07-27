"""Crash report schemas.

``CrashReportSubmit`` is deliberately permissive: it is the contract with
firmware in the field, which cannot be redeployed as easily as this service.
Normalisation happens in :mod:`app.services.crash_parser`, so the schema only
enforces what would make a report unusable.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import AliasChoices, ConfigDict, Field, model_validator

from app.models.crash import CrashSeverity, CrashStatus, FaultType
from app.schemas.common import BaseSchema
from app.schemas.device import DeviceSummary
from app.services.crash_parser import FIELD_ALIASES


def _aliases(canonical: str) -> AliasChoices:
    """Accept every field spelling the parser understands.

    Sourced from the parser's own alias table rather than restated here: a
    schema that rejected ``firmwareVersion`` before the parser saw it would
    make the parser's tolerance unreachable, and two hand-maintained lists
    would drift apart the first time a new firmware dialect appeared.
    """
    return AliasChoices(*FIELD_ALIASES[canonical])


class CrashReportSubmit(BaseSchema):
    """Payload posted by a device (or by an engineer on its behalf).

    Extra fields are preserved rather than rejected: unknown keys are kept in
    ``raw_payload`` so a firmware revision that adds a field does not start
    failing against an older server.
    """

    model_config = ConfigDict(extra="allow", from_attributes=True, populate_by_name=True)

    device_id: str | None = Field(
        default=None,
        max_length=64,
        validation_alias=_aliases("device_identifier"),
        description=(
            "Device identifier or serial. Optional when authenticating with a "
            "device API key, which already identifies the device."
        ),
        examples=["STM32-F4-0001"],
    )
    firmware_version: str = Field(
        max_length=50, validation_alias=_aliases("firmware_version"), examples=["1.4.2"]
    )
    timestamp: str | int | float | None = Field(
        default=None,
        validation_alias=_aliases("occurred_at"),
        description="ISO-8601 or epoch seconds/milliseconds. Defaults to time of receipt.",
        examples=["2026-07-27T09:14:22Z"],
    )
    fault_type: str | None = Field(
        default=None,
        max_length=60,
        validation_alias=_aliases("fault_type"),
        description="Free-form; normalised to a known fault type.",
        examples=["HardFault"],
    )
    exception_type: str | None = Field(
        default=None, max_length=100, validation_alias=_aliases("exception_type")
    )
    task_name: str | None = Field(
        default=None,
        max_length=100,
        validation_alias=_aliases("task_name"),
        examples=["SensorTask"],
    )
    program_counter: str | int | None = Field(
        default=None, validation_alias=_aliases("program_counter"), examples=["0x08001A2C"]
    )
    link_register: str | int | None = Field(
        default=None, validation_alias=_aliases("link_register"), examples=["0x08001A0F"]
    )
    stack_pointer: str | int | None = Field(
        default=None, validation_alias=_aliases("stack_pointer"), examples=["0x20017FA0"]
    )
    register_dump: dict[str, Any] | list[Any] | None = Field(
        default=None,
        validation_alias=_aliases("registers"),
        examples=[{"r0": "0x00000000", "r1": "0x20000100", "psr": "0x61000000"}],
    )
    stack_dump: dict[str, Any] | list[Any] | str | None = Field(
        default=None,
        validation_alias=_aliases("stack"),
        examples=[["0x0800 1A2C", "0x20017FB0"]],
    )
    build_version: str | None = Field(
        default=None,
        max_length=100,
        validation_alias=_aliases("build_version"),
        examples=["a1b2c3d"],
    )
    severity: str | None = Field(
        default=None,
        max_length=20,
        validation_alias=_aliases("severity"),
        description="Overrides the derived severity.",
    )
    notes: str | None = Field(default=None, max_length=5000, validation_alias=_aliases("notes"))

    @model_validator(mode="after")
    def _reject_empty_report(self) -> CrashReportSubmit:
        """A report with no fault evidence at all is a bug, not a crash."""
        evidence = (
            self.fault_type,
            self.exception_type,
            self.program_counter,
            self.link_register,
            self.stack_pointer,
            self.register_dump,
            self.stack_dump,
        )
        if not any(value is not None for value in evidence):
            raise ValueError(
                "report must contain at least one of: fault_type, exception_type, "
                "program_counter, link_register, stack_pointer, register_dump, stack_dump"
            )
        return self


class CrashReportUpdate(BaseSchema):
    """Engineer triage. Fault evidence is immutable — only triage fields change."""

    status: CrashStatus | None = None
    severity: CrashSeverity | None = None
    notes: str | None = Field(default=None, max_length=5000)


class CrashReportRead(BaseSchema):
    """Full crash report."""

    id: uuid.UUID
    device: DeviceSummary
    firmware_version: str
    build_version: str | None = None
    occurred_at: datetime
    received_at: datetime

    fault_type: FaultType
    exception_type: str | None = None
    task_name: str | None = None
    program_counter: int | None = None
    link_register: int | None = None
    stack_pointer: int | None = None
    register_dump: dict[str, Any] | None = None
    stack_dump: dict[str, Any] | None = None

    severity: CrashSeverity
    status: CrashStatus
    notes: str | None = None

    ai_diagnosis: str | None = None
    suggested_fix: str | None = None
    confidence_score: float | None = None
    diagnosed_at: datetime | None = None

    parse_warnings: dict[str, Any] | None = None
    parser_version: str | None = None
    created_at: datetime

    @property
    def program_counter_hex(self) -> str | None:
        return f"0x{self.program_counter:08X}" if self.program_counter is not None else None


class CrashReportListItem(BaseSchema):
    """Row projection for the crash history table.

    Register and stack dumps are omitted: a page of 50 crashes would otherwise
    ship megabytes of hex the table never renders.
    """

    id: uuid.UUID
    device: DeviceSummary
    firmware_version: str
    occurred_at: datetime
    fault_type: FaultType
    task_name: str | None = None
    program_counter: int | None = None
    severity: CrashSeverity
    status: CrashStatus
    confidence_score: float | None = None


class CrashAccepted(BaseSchema):
    """Acknowledgement returned to a device after ingestion."""

    id: uuid.UUID
    status: CrashStatus
    severity: CrashSeverity
    fault_type: FaultType
    received_at: datetime
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal parsing issues. The report was still stored.",
    )
