"""Device fleet models: devices, tags and per-device ingestion keys."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import GUID, Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.crash import CrashReport
    from app.models.user import User


class DeviceStatus(StrEnum):
    """Operational state of a device.

    Stored explicitly rather than derived from ``last_online_at`` alone: a
    decommissioned device and one that simply has not phoned in are different
    facts, and only the fleet owner knows which is which.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"
    DECOMMISSIONED = "decommissioned"


#: Many-to-many association between devices and tags.
device_tags = Table(
    "device_tags",
    Base.metadata,
    Column("device_id", GUID(), ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", GUID(), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Tag(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A free-form label applied to devices.

    Modelled as a table rather than a JSON array so tags can be listed,
    renamed and filtered on with an ordinary indexed join.
    """

    __tablename__ = "tags"

    name: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)

    devices: Mapped[list[Device]] = relationship(
        secondary=device_tags, back_populates="tags", lazy="noload"
    )

    @staticmethod
    def normalize(name: str) -> str:
        """Tags are compared case-insensitively and stored lower-cased."""
        return name.strip().lower()


class Device(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A physical embedded device that reports crashes."""

    __tablename__ = "devices"

    #: Firmware-facing identifier, e.g. "STM32-F4-0001". Used by devices when
    #: they submit crash reports, so it is unique and immutable in practice.
    device_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    serial_number: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    firmware_version: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    hardware_model: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=DeviceStatus.ACTIVE, index=True, nullable=False
    )
    location: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(500))

    #: Nullable and ``ON DELETE SET NULL``: deleting a user must not delete the
    #: fleet they happened to own.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    last_online_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    owner: Mapped[User | None] = relationship(lazy="selectin")
    tags: Mapped[list[Tag]] = relationship(
        secondary=device_tags, back_populates="devices", lazy="selectin"
    )
    # ``passive_deletes`` lets the FK's ON DELETE CASCADE do the work: a device
    # can have hundreds of thousands of crash reports, and loading them all into
    # the session just to delete them would be ruinous.
    api_keys: Mapped[list[DeviceApiKey]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
        lazy="noload",
        passive_deletes=True,
    )
    crash_reports: Mapped[list[CrashReport]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
        lazy="noload",
        passive_deletes=True,
    )

    @property
    def tag_names(self) -> list[str]:
        return sorted(tag.name for tag in self.tags)

    @property
    def is_operational(self) -> bool:
        return self.status in (DeviceStatus.ACTIVE, DeviceStatus.MAINTENANCE)


class DeviceApiKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Credential a device uses to submit crash reports.

    Devices cannot perform an interactive login, so they authenticate with a
    long-lived key instead of a JWT. Only the hash is stored; the plaintext is
    shown once at creation.
    """

    __tablename__ = "device_api_keys"
    __table_args__ = (UniqueConstraint("key_hash", name="uq_device_api_keys_key_hash"),)

    device_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("devices.id", ondelete="CASCADE"), index=True, nullable=False
    )
    #: Non-secret leading segment, used to look the row up before hashing and
    #: to identify a key in the UI without revealing it.
    prefix: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    device: Mapped[Device] = relationship(back_populates="api_keys", lazy="selectin")

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None
