"""Knowledge-base documents and their embedded chunks."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
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


class DocumentSourceType(StrEnum):
    """What kind of knowledge a document carries.

    Stored so retrieval can be scoped — diagnosing a FreeRTOS task fault can
    prefer FreeRTOS docs — and so the UI can group the library.
    """

    STM32_REFERENCE = "stm32_reference"
    FREERTOS_DOC = "freertos_doc"
    ARM_CORTEX_M = "arm_cortex_m"
    ENGINEERING_NOTE = "engineering_note"
    TROUBLESHOOTING = "troubleshooting"
    APPLICATION_NOTE = "application_note"
    PREVIOUS_CRASH = "previous_crash"
    OTHER = "other"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One uploaded knowledge-base document.

    The full text is kept so a document can be re-chunked when the chunking
    strategy changes, exactly as crash reports keep their raw payload.
    """

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_documents_content_hash"),
        Index("ix_documents_source_type_status", "source_type", "status"),
    )

    title: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(30), default=DocumentSourceType.OTHER, index=True, nullable=False
    )
    #: Original filename, when uploaded as a file rather than pasted text.
    original_filename: Mapped[str | None] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(50), default="text/plain", nullable=False)
    #: The full extracted text. Source of truth for re-chunking.
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: Deduplicates re-uploads of the same content.
    content_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    #: Free-form tags/metadata, e.g. {"chip": "STM32F407", "version": "rev9"}.
    doc_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONType)

    status: Mapped[str] = mapped_column(
        String(20), default=DocumentStatus.PENDING, index=True, nullable=False
    )
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: Which embedding model produced this document's vectors. A document
    #: embedded with a different model than the query cannot be compared, so
    #: retrieval filters on it.
    embedding_model: Mapped[str | None] = mapped_column(String(100), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )

    uploaded_by: Mapped[User | None] = relationship(lazy="selectin")
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="noload",
        passive_deletes=True,
    )

    @property
    def is_indexed(self) -> bool:
        return self.status == DocumentStatus.INDEXED and self.chunk_count > 0


class DocumentChunk(UUIDPrimaryKeyMixin, Base):
    """A chunk of a document, with its embedding.

    The embedding is stored inline as a JSON array so the default database
    vector store needs no extra infrastructure; a ChromaDB backend keeps the
    same rows and stores vectors alongside. No ``updated_at``: chunks are
    written once when a document is indexed.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("ix_document_chunks_document_id_index", "document_id", "chunk_index"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    #: Position within the document, so retrieved context can be shown in order.
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: The embedding vector. Null only transiently, before embedding completes.
    embedding: Mapped[list[float] | None] = mapped_column(JSONType)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: Denormalised from the parent document so a retrieval hit is
    #: self-describing without a join.
    source_type: Mapped[str | None] = mapped_column(String(30), index=True)
    document_title: Mapped[str | None] = mapped_column(String(255))

    document: Mapped[Document] = relationship(back_populates="chunks", lazy="noload")
