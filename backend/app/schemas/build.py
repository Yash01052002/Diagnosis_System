"""Firmware build and crash-group schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from app.models.build import ArtifactType, BuildStatus
from app.models.crash import CrashSeverity, FaultType
from app.models.crash_group import CrashGroupStatus
from app.schemas.common import BaseSchema
from app.schemas.user import UserSummary


class FirmwareBuildRead(BaseSchema):
    """An uploaded build artifact.

    ``storage_path`` is deliberately absent: server filesystem layout is not
    something an API client has any business knowing.
    """

    id: uuid.UUID
    firmware_version: str
    build_version: str | None = None
    hardware_model: str | None = None
    artifact_type: ArtifactType
    original_filename: str
    file_size: int
    sha256: str
    build_id: str | None = Field(
        default=None, description="GNU build id from the ELF note, when present."
    )
    status: BuildStatus
    arch: str | None = None
    has_debug_info: bool
    symbol_count: int
    entry_point: int | None = None
    error_message: str | None = None
    notes: str | None = None
    indexed_at: datetime | None = None
    created_at: datetime
    uploaded_by: UserSummary | None = None
    parse_warnings: list[str] = Field(default_factory=list)

    @field_validator("parse_warnings", mode="before")
    @classmethod
    def unwrap_warnings(cls, value: object) -> object:
        """Flatten the stored ``{"warnings": [...]}`` envelope."""
        if isinstance(value, dict):
            return value.get("warnings", [])
        return value or []


class FirmwareBuildSummary(BaseSchema):
    """Lightweight projection embedded in a symbolized crash."""

    id: uuid.UUID
    firmware_version: str
    build_version: str | None = None
    artifact_type: ArtifactType
    has_debug_info: bool
    symbol_count: int


class BuildUploadResult(FirmwareBuildRead):
    """Returned after an upload, with what indexing achieved."""

    message: str = Field(
        description="Human-readable summary of what was indexed.",
        examples=["Indexed 1,284 symbols with debug info."],
    )


class ResymbolicateRequest(BaseSchema):
    """Ask for stored crashes to be re-processed against current builds."""

    firmware_version: str | None = Field(
        default=None,
        max_length=50,
        description="Defaults to the build's own firmware version.",
    )
    build_version: str | None = Field(default=None, max_length=100)
    limit: int = Field(default=500, ge=1, le=5000, description="Maximum reports to process.")


class ResymbolicateResult(BaseSchema):
    processed: int
    upgraded: int = Field(description="Reports that now resolve at least one symbol.")
    total_matching: int


# ---------------------------------------------------------------------------
# Symbolication output
# ---------------------------------------------------------------------------
class FrameRead(BaseSchema):
    """One resolved stack frame."""

    address: int
    address_hex: str
    origin: str = Field(description='Where the address came from: "pc", "lr" or "stack".')
    function: str | None = None
    offset: int | None = None
    source_file: str | None = None
    line: int | None = None
    resolved: bool
    thumb: bool = False
    inlined: bool = False
    display: str = Field(examples=["vTaskDelay+0x1c at tasks.c:1432"])


class SymbolicationRead(BaseSchema):
    """The symbolized view of a crash."""

    symbolized: bool
    build_version: str | None = None
    pc: FrameRead | None = None
    lr: FrameRead | None = None
    frames: list[FrameRead] = Field(default_factory=list)
    resolved_count: int = 0
    frame_count: int = 0
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Crash groups
# ---------------------------------------------------------------------------
class CrashGroupRead(BaseSchema):
    """A set of crash reports sharing one signature."""

    id: uuid.UUID
    signature: str
    title: str
    fault_type: FaultType
    task_name: str | None = None
    top_function: str | None = None
    status: CrashGroupStatus
    severity: CrashSeverity
    occurrence_count: int
    device_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    regressed_at: datetime | None = None
    notes: str | None = None
    affected_firmware_versions: list[str] = Field(default_factory=list)
    signature_components: dict[str, Any] | None = Field(
        default=None, description="The inputs the signature was computed from."
    )

    @field_validator("affected_firmware_versions", mode="before")
    @classmethod
    def unwrap_versions(cls, value: object) -> object:
        if isinstance(value, dict):
            return value.get("versions", [])
        return value or []


class CrashGroupSummary(BaseSchema):
    """Projection embedded in a crash report."""

    id: uuid.UUID
    signature: str
    title: str
    status: CrashGroupStatus
    occurrence_count: int
    device_count: int


class CrashGroupUpdate(BaseSchema):
    """Triage of the underlying defect, not of one occurrence."""

    status: CrashGroupStatus | None = None
    notes: str | None = Field(default=None, max_length=5000)
