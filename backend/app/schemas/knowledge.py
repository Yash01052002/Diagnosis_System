"""Knowledge-base and diagnosis schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.models.diagnosis import ConfidenceLabel
from app.models.document import DocumentSourceType, DocumentStatus
from app.schemas.common import BaseSchema
from app.schemas.user import UserSummary


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
class DocumentCreate(BaseSchema):
    """Ingest a document from pasted text."""

    title: str = Field(min_length=1, max_length=255, examples=["STM32F4 HardFault notes"])
    content: str = Field(min_length=1, description="The full document text.")
    source_type: DocumentSourceType = DocumentSourceType.OTHER
    metadata: dict[str, Any] | None = Field(
        default=None, examples=[{"chip": "STM32F407", "revision": "9"}]
    )


class DocumentRead(BaseSchema):
    id: uuid.UUID
    title: str
    source_type: DocumentSourceType
    original_filename: str | None = None
    content_type: str
    status: DocumentStatus
    chunk_count: int
    embedding_model: str | None = None
    error_message: str | None = None
    doc_metadata: dict[str, Any] | None = None
    indexed_at: datetime | None = None
    created_at: datetime
    uploaded_by: UserSummary | None = None


class DocumentSummary(BaseSchema):
    id: uuid.UUID
    title: str
    source_type: DocumentSourceType
    status: DocumentStatus
    chunk_count: int


class KnowledgeBaseStats(BaseSchema):
    documents: int
    chunks: int
    embedding_provider: str
    vector_store: str


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
class SearchRequest(BaseSchema):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=6, ge=1, le=25)
    source_types: list[DocumentSourceType] | None = None


class RetrievedChunkRead(BaseSchema):
    document_id: uuid.UUID
    document_title: str | None = None
    source_type: str | None = None
    chunk_index: int
    score: float = Field(description="Cosine similarity to the query, 0-1.")
    content: str


class SearchResponse(BaseSchema):
    query: str
    results: list[RetrievedChunkRead]
    #: True when nothing cleared the relevance floor — the query found no
    #: usable reference material.
    empty: bool


# ---------------------------------------------------------------------------
# Diagnoses
# ---------------------------------------------------------------------------
class DiagnosisSource(BaseSchema):
    document_id: uuid.UUID | None = None
    document_title: str | None = None
    source_type: str | None = None
    chunk_index: int | None = None
    score: float | None = None
    excerpt: str | None = None


class DiagnosisRead(BaseSchema):
    id: uuid.UUID
    crash_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    root_cause: str
    recommended_fix: str | None = None
    summary: str | None = None
    confidence_score: float
    confidence_label: ConfidenceLabel
    is_uncertain: bool = Field(
        description="True when the diagnosis is not well grounded in the knowledge base."
    )
    top_relevance: float | None = None
    sources: list[DiagnosisSource] = Field(default_factory=list)
    provider: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int | None = None
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime
    requested_by: UserSummary | None = None

    @classmethod
    def from_model(cls, diagnosis: Any) -> DiagnosisRead:
        """Build from an ``AiDiagnosis``, flattening the stored JSON envelopes."""
        warnings = (diagnosis.warnings or {}).get("warnings", []) if diagnosis.warnings else []
        return cls(
            id=diagnosis.id,
            crash_id=diagnosis.crash_id,
            group_id=diagnosis.group_id,
            root_cause=diagnosis.root_cause,
            recommended_fix=diagnosis.recommended_fix,
            summary=diagnosis.summary,
            confidence_score=diagnosis.confidence_score,
            confidence_label=ConfidenceLabel(diagnosis.confidence_label),
            is_uncertain=diagnosis.is_uncertain,
            top_relevance=diagnosis.top_relevance,
            sources=[DiagnosisSource.model_validate(s) for s in (diagnosis.sources or [])],
            provider=diagnosis.provider,
            model=diagnosis.model,
            prompt_tokens=diagnosis.prompt_tokens,
            completion_tokens=diagnosis.completion_tokens,
            latency_ms=diagnosis.latency_ms,
            warnings=warnings,
            created_at=diagnosis.created_at,
            requested_by=(
                UserSummary.model_validate(diagnosis.requested_by)
                if diagnosis.requested_by
                else None
            ),
        )
