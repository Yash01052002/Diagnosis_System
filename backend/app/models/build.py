"""Firmware build artifacts and their extracted symbol tables."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import GUID, Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class BuildStatus(StrEnum):
    """Lifecycle of an uploaded artifact."""

    PENDING = "pending"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"


class ArtifactType(StrEnum):
    ELF = "elf"
    MAP = "map"


class FirmwareBuild(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An uploaded ELF or MAP file for one firmware build.

    Crash reports reference a build by ``firmware_version`` and
    ``build_version``: those are the two identifiers a device reports, so they
    are what symbolization has to match on.
    """

    __tablename__ = "firmware_builds"
    __table_args__ = (
        # One artifact per (firmware, build, type). Re-uploading replaces it.
        UniqueConstraint(
            "firmware_version",
            "build_version",
            "artifact_type",
            name="uq_firmware_builds_version_build_type",
        ),
        Index("ix_firmware_builds_firmware_build", "firmware_version", "build_version"),
    )

    firmware_version: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    #: Git SHA or CI build number. Nullable: not every build has one, and a
    #: firmware version alone is often enough to identify the image.
    build_version: Mapped[str | None] = mapped_column(String(100), index=True)
    hardware_model: Mapped[str | None] = mapped_column(String(100), index=True)

    artifact_type: Mapped[str] = mapped_column(String(10), default=ArtifactType.ELF, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Path on the artifact volume. Not exposed through the API.
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: Content hash, so a re-upload of an identical file is recognisable.
    sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    #: GNU build id from the ELF note, when present.
    build_id: Mapped[str | None] = mapped_column(String(64), index=True)

    status: Mapped[str] = mapped_column(
        String(20), default=BuildStatus.PENDING, index=True, nullable=False
    )
    arch: Mapped[str | None] = mapped_column(String(30))
    has_debug_info: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    symbol_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    entry_point: Mapped[int | None] = mapped_column(BigInteger)
    #: Executable address ranges, used to filter stack-scan candidates.
    sections: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    parse_warnings: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    error_message: Mapped[str | None] = mapped_column(Text)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(String(500))

    uploaded_by: Mapped[User | None] = relationship(lazy="selectin")
    symbols: Mapped[list[BuildSymbol]] = relationship(
        back_populates="build",
        cascade="all, delete-orphan",
        lazy="noload",
        passive_deletes=True,
    )

    @property
    def is_usable(self) -> bool:
        """True when this build can actually symbolize an address."""
        return self.status == BuildStatus.INDEXED and self.symbol_count > 0


class BuildSymbol(UUIDPrimaryKeyMixin, Base):
    """One symbol from a build's symbol table.

    Stored in the database rather than re-read from the ELF on every lookup:
    resolving a name is then an indexed range query, and it keeps working even
    if the artifact file is later pruned from disk. Source lines still need
    the file, so they degrade to ``function+offset`` in that case.

    Deliberately has no ``updated_at``: symbols are written once when a build
    is indexed and never modified, and a firmware image can carry tens of
    thousands of them.
    """

    __tablename__ = "build_symbols"
    __table_args__ = (
        # The hot query is "which symbol covers this address in this build".
        Index("ix_build_symbols_build_address", "build_id", "address"),
        Index("ix_build_symbols_build_name", "build_id", "name"),
    )

    build_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("firmware_builds.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Thumb bit already cleared. BigInteger because a signed 32-bit column
    #: cannot hold addresses above 0x7FFFFFFF.
    address: Mapped[int] = mapped_column(BigInteger, nullable=False)
    size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    kind: Mapped[str] = mapped_column(String(10), default="func", nullable=False)

    build: Mapped[FirmwareBuild] = relationship(back_populates="symbols", lazy="noload")
