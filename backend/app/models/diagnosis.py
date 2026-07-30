"""AI crash diagnosis records."""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import GUID, Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.crash import CrashReport
    from app.models.crash_group import CrashGroup
    from app.models.user import User


class ConfidenceLabel(StrEnum):
    """A human-facing band for the confidence score.

    The band is derived, never taken from the model's own claim: an LLM will
    happily report high confidence in a fabrication. ``UNCERTAIN`` is the
    anti-hallucination signal — when retrieval found little to ground an
    answer, the diagnosis says so plainly instead of guessing.
    """

    CERTAIN = "certain"
    LIKELY = "likely"
    UNCERTAIN = "uncertain"


class AiDiagnosis(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One AI-generated diagnosis of a crash (or a crash group).

    History is kept rather than overwritten: re-running after uploading a
    relevant manual should let an engineer compare, not silently replace the
    earlier answer.
    """

    __tablename__ = "ai_diagnoses"
    __table_args__ = (
        Index("ix_ai_diagnoses_crash_id_created", "crash_id", "created_at"),
    )

    #: The crash this diagnosis is for. Nullable because a diagnosis can target
    #: a whole group (the bug) rather than one occurrence.
    crash_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("crash_reports.id", ondelete="CASCADE"), index=True
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("crash_groups.id", ondelete="CASCADE"), index=True
    )

    root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_fix: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(String(500))

    #: 0.0-1.0, grounded in retrieval quality, not the model's self-report.
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    confidence_label: Mapped[str] = mapped_column(
        String(20), default=ConfidenceLabel.UNCERTAIN, index=True, nullable=False
    )
    #: True when the answer is not well grounded. Surfaced prominently so a
    #: shaky diagnosis is never mistaken for a confident one.
    is_uncertain: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    #: The retrieved chunks the answer was built from:
    #: [{"document_id", "document_title", "chunk_index", "score", "excerpt"}].
    #: Stored so every diagnosis is auditable back to its sources.
    sources: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONType)
    #: Highest retrieval similarity, the basis of the confidence band.
    top_relevance: Mapped[float | None] = mapped_column(Float)

    # -- provenance ----------------------------------------------------
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    #: The exact prompt sent, kept for reproducibility and debugging.
    prompt: Mapped[str | None] = mapped_column(Text)
    #: Non-fatal issues (weak retrieval, truncation, parse fallback).
    warnings: Mapped[dict[str, Any] | None] = mapped_column(JSONType)

    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )

    crash: Mapped[CrashReport | None] = relationship(lazy="noload")
    group: Mapped[CrashGroup | None] = relationship(lazy="noload")
    requested_by: Mapped[User | None] = relationship(lazy="selectin")

    @property
    def source_count(self) -> int:
        return len(self.sources or [])
