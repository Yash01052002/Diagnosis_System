"""Knowledge-base ingestion and search.

Turns an uploaded document into retrievable, embedded chunks, and answers
semantic-search queries over them.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.audit_log import AuditAction
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.user import User
from app.repositories.document import DocumentChunkRepository, DocumentRepository
from app.services.ai.chunking import chunk_text, normalize_text
from app.services.ai.embeddings import EmbeddingProvider
from app.services.ai.vector_store import RetrievedChunk, VectorStore
from app.services.audit import AuditService
from app.services.auth import RequestContext

logger = get_logger(__name__)


class KnowledgeBaseService:
    """Ingests documents and serves retrieval."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        documents: DocumentRepository,
        chunks: DocumentChunkRepository,
        embedder: EmbeddingProvider,
        vector_store: VectorStore,
        audit: AuditService,
        settings: Settings,
    ) -> None:
        self.session = session
        self.documents = documents
        self.chunks = chunks
        self.embedder = embedder
        self.vector_store = vector_store
        self.audit = audit
        self.settings = settings

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    async def get(self, document_id: uuid.UUID) -> Document:
        document = await self.documents.get(document_id)
        if document is None:
            raise NotFoundError("Document not found.")
        return document

    async def search(
        self,
        *,
        query: str | None = None,
        source_type: str | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[Document], int]:
        return await self.documents.search(
            query=query, source_type=source_type, status=status, offset=offset, limit=limit
        )

    async def stats(self) -> dict[str, int]:
        return await self.documents.stats()

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------
    async def ingest(
        self,
        *,
        title: str,
        content: str,
        source_type: str,
        original_filename: str | None = None,
        content_type: str = "text/plain",
        metadata: dict | None = None,
        actor: User,
        ctx: RequestContext | None = None,
    ) -> Document:
        """Store, chunk and embed a document.

        Runs inline: for a firmware manual this is a handful of embedding calls,
        and an engineer uploading a document wants to know immediately that it
        indexed. Re-uploading identical content is rejected as a conflict rather
        than silently duplicating the corpus.

        Raises:
            ValidationError: the document is empty or too large.
            ConflictError: the same content is already in the knowledge base.
        """
        ctx = ctx or RequestContext()
        cleaned = normalize_text(content)
        if not cleaned:
            raise ValidationError("Document content is empty.")
        size = len(cleaned.encode("utf-8"))
        if size > self.settings.MAX_DOCUMENT_SIZE_MB * 1024 * 1024:
            raise ValidationError(
                f"Document exceeds the {self.settings.MAX_DOCUMENT_SIZE_MB} MB limit."
            )

        content_hash = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
        existing = await self.documents.get_by_hash(content_hash)
        if existing is not None:
            raise ConflictError(
                "This exact content is already in the knowledge base.",
                details={"document_id": str(existing.id), "title": existing.title},
            )

        document = Document(
            title=title.strip()[:255],
            source_type=source_type,
            original_filename=original_filename,
            content_type=content_type,
            content=cleaned,
            content_hash=content_hash,
            doc_metadata=metadata,
            status=DocumentStatus.PROCESSING,
            embedding_model=self.embedder.name,
        )
        self.documents.add(document)
        await self.session.flush()

        try:
            chunk_count = await self._chunk_and_embed(document, cleaned)
        except Exception as exc:  # noqa: BLE001 - record the failure, don't 500
            document.status = DocumentStatus.FAILED
            document.error_message = str(exc)[:2000]
            await self.session.commit()
            logger.error("kb.ingest_failed", document_id=str(document.id), error=str(exc))
            raise ValidationError(
                f"Could not index the document: {exc}", details={"title": title}
            ) from exc

        document.status = DocumentStatus.INDEXED
        document.chunk_count = chunk_count
        document.indexed_at = datetime.now(UTC)

        await self.audit.record(
            AuditAction.DOCUMENT_UPLOADED,
            actor_id=actor.id,
            actor_email=actor.email,
            resource_type="document",
            resource_id=document.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            context={"title": title, "source_type": source_type, "chunks": chunk_count},
        )
        await self.session.commit()
        logger.info(
            "kb.ingested",
            document_id=str(document.id),
            chunks=chunk_count,
            model=self.embedder.name,
        )
        return await self.get(document.id)

    async def _chunk_and_embed(self, document: Document, text: str) -> int:
        """Split ``text``, embed every chunk and persist the rows."""
        pieces = chunk_text(
            text,
            chunk_size=self.settings.CHUNK_SIZE,
            overlap=self.settings.CHUNK_OVERLAP,
        )
        if not pieces:
            raise ValueError("the document produced no chunks")

        embeddings = await self.embedder.embed([piece.content for piece in pieces])
        rows = [
            DocumentChunk(
                document_id=document.id,
                chunk_index=piece.index,
                content=piece.content,
                embedding=embedding,
                token_count=piece.token_estimate,
                source_type=document.source_type,
                document_title=document.title,
            )
            for piece, embedding in zip(pieces, embeddings, strict=True)
        ]
        await self.chunks.bulk_insert(rows)
        return len(rows)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    async def retrieve(
        self,
        query: str,
        *,
        top_k: int | None = None,
        source_types: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        """Return the chunks most relevant to ``query``.

        Embeds the query with the same provider the documents were indexed
        with, so the vectors are comparable, and filters out chunks below the
        relevance floor — the first line of the anti-hallucination defence.
        """
        embedding = await self.embedder.embed_one(query)
        hits = await self.vector_store.search(
            embedding,
            top_k=top_k or self.settings.RAG_TOP_K,
            embedding_model=self.embedder.name,
            source_types=source_types,
        )
        return [hit for hit in hits if hit.score >= self.settings.RAG_MIN_RELEVANCE]

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------
    async def delete(
        self, document_id: uuid.UUID, *, actor: User, ctx: RequestContext | None = None
    ) -> None:
        ctx = ctx or RequestContext()
        document = await self.get(document_id)

        await self.audit.record(
            AuditAction.DOCUMENT_DELETED,
            actor_id=actor.id,
            actor_email=actor.email,
            resource_type="document",
            resource_id=document.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            context={"title": document.title, "chunks": document.chunk_count},
        )
        # Chunks cascade in the database; that also clears the vectors, since
        # the database store keeps them on the chunk rows.
        await self.documents.delete(document)
        await self.session.commit()
        logger.info("kb.deleted", document_id=str(document_id))
