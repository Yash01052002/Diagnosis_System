"""Device, tag and API-key schemas."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field, field_validator

from app.models.device import DeviceStatus
from app.schemas.common import BaseSchema
from app.schemas.user import UserSummary

#: Device identifiers and serials come from manufacturing systems, so they are
#: restricted to characters that survive URLs, CSV exports and shell scripts.
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,63}$")
_TAG = re.compile(r"^[a-z0-9][a-z0-9 ._-]{0,49}$")

DeviceIdentifier = Annotated[str, Field(min_length=2, max_length=64)]


def _validate_identifier(value: str) -> str:
    value = value.strip()
    if not _IDENTIFIER.match(value):
        raise ValueError(
            "must start with a letter or digit and contain only letters, digits, "
            "'.', '_', ':' or '-'"
        )
    return value


def normalize_tags(value: list[str]) -> list[str]:
    """Normalise, de-duplicate and validate tag names."""
    normalized: list[str] = []
    for raw in value:
        tag = raw.strip().lower()
        if not tag:
            continue
        if not _TAG.match(tag):
            raise ValueError(f"invalid tag {raw!r}: use letters, digits, spaces, '.', '_' or '-'")
        if tag not in normalized:
            normalized.append(tag)
    return normalized


class TagRead(BaseSchema):
    id: uuid.UUID
    name: str


class DeviceBase(BaseSchema):
    firmware_version: str = Field(max_length=50, examples=["1.4.2"])
    hardware_model: str = Field(max_length=100, examples=["STM32F407VG"])
    location: str | None = Field(default=None, max_length=255, examples=["Lab A, Rack 3"])
    description: str | None = Field(default=None, max_length=500)
    tags: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Free-form labels. Compared case-insensitively.",
        examples=[["field-trial", "eu-west"]],
    )

    _check_tags = field_validator("tags")(normalize_tags)


class DeviceCreate(DeviceBase):
    device_id: DeviceIdentifier = Field(
        description="Identifier the firmware reports with.", examples=["STM32-F4-0001"]
    )
    serial_number: DeviceIdentifier = Field(examples=["SN-2026-000123"])
    status: DeviceStatus = DeviceStatus.ACTIVE
    owner_id: uuid.UUID | None = Field(
        default=None, description="Defaults to the user creating the device."
    )

    _check_device_id = field_validator("device_id")(_validate_identifier)
    _check_serial = field_validator("serial_number")(_validate_identifier)


class DeviceUpdate(BaseSchema):
    """Partial update. ``device_id`` and ``serial_number`` are immutable.

    Those two identify the physical unit and appear in every crash report the
    device has ever sent; letting them change would silently rewrite history.
    """

    firmware_version: str | None = Field(default=None, max_length=50)
    hardware_model: str | None = Field(default=None, max_length=100)
    status: DeviceStatus | None = None
    location: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    owner_id: uuid.UUID | None = None
    tags: list[str] | None = Field(default=None, max_length=20)

    @field_validator("tags")
    @classmethod
    def _check_tags(cls, value: list[str] | None) -> list[str] | None:
        return normalize_tags(value) if value is not None else None


class DeviceRead(DeviceBase):
    id: uuid.UUID
    device_id: str
    serial_number: str
    status: DeviceStatus
    last_online_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    owner: UserSummary | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("tags", mode="before")
    @classmethod
    def flatten_tags(cls, value: object) -> object:
        """Serialise the ``Tag`` relationship as a list of names."""
        if isinstance(value, list):
            return [item if isinstance(item, str) else item.name for item in value]
        return value


class DeviceSummary(BaseSchema):
    """Lightweight projection embedded in crash reports."""

    id: uuid.UUID
    device_id: str
    serial_number: str
    hardware_model: str
    status: DeviceStatus


class DeviceHeartbeat(BaseSchema):
    """Optional body for a device check-in."""

    firmware_version: str | None = Field(
        default=None,
        max_length=50,
        description="Reported on check-in so an OTA update is reflected without an edit.",
    )
    status: DeviceStatus | None = None


class DeviceStats(BaseSchema):
    """Crash counts for a single device."""

    device_id: uuid.UUID
    total_crashes: int
    open_crashes: int
    crashes_last_24h: int
    last_crash_at: datetime | None = None


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
class DeviceApiKeyCreate(BaseSchema):
    name: str = Field(max_length=100, examples=["field-trial-fleet"])
    expires_at: datetime | None = Field(
        default=None, description="Optional expiry. Omit for a non-expiring key."
    )


class DeviceApiKeyRead(BaseSchema):
    id: uuid.UUID
    device_id: uuid.UUID
    name: str
    prefix: str = Field(description="Non-secret identifier shown in the UI.")
    created_at: datetime
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class DeviceApiKeyCreated(DeviceApiKeyRead):
    """Returned once, at creation."""

    api_key: str = Field(
        description="The full key. Store it now - it is never shown again.",
        examples=["bbx_a1b2c3d4_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"],
    )
