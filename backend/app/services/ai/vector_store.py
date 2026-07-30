"""Vector stores for knowledge-base retrieval.

The default ``DatabaseVectorStore`` keeps embeddings in PostgreSQL (on the
``document_chunks`` rows) and scores them in Python with NumPy — no extra
infrastructure, works in every environment including the test suite. A
``ChromaVectorStore`` is available for larger corpora, behind the same
interface.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.document import DocumentChunk


@dataclass(slots=True)
class RetrievedChunk:
    """A chunk returned by a similarity search, with its score."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str | None
    source_type: str | None
    chunk_index: int
    content: str
    score: float


class VectorStore(ABC):
    """Similarity search over embedded chunks."""

    @abstractmethod
    async def search(
        self,
        query_embedding: list[float],
        *,
        top_k: int,
        embedding_model: str,
        source_types: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        """Return the ``top_k`` most similar chunks, highest score first."""


def cosine_similarity(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Cosine similarity between one vector and each row of ``matrix``.

    Rows and the query are L2-normalised first; a zero vector yields a score
    of 0 rather than a divide-by-zero.
    """
    if matrix.size == 0:
        return np.array([])
    query_norm = np.linalg.norm(query)
    if query_norm == 0:
        return np.zeros(matrix.shape[0])
    row_norms = np.linalg.norm(matrix, axis=1)
    row_norms[row_norms == 0] = 1.0
    return (matrix @ query) / (row_norms * query_norm)


class DatabaseVectorStore(VectorStore):
    """Brute-force cosine search over chunks stored in the database.

    Loading every embedding for the matching model into memory is fine for the
    thousands-of-chunks corpus a firmware knowledge base realistically holds,
    and it keeps the deployment to a single database. ``ChromaVectorStore`` is
    the escape hatch when the corpus outgrows that.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(
        self,
        query_embedding: list[float],
        *,
        top_k: int,
        embedding_model: str,
        source_types: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        # Only compare against chunks embedded with the same model — vectors
        # from different models are not comparable.
        stmt = (
            select(DocumentChunk)
            .join(DocumentChunk.document)
            .where(DocumentChunk.embedding.isnot(None))
        )
        from app.models.document import Document

        stmt = stmt.where(Document.embedding_model == embedding_model)
        if source_types:
            stmt = stmt.where(DocumentChunk.source_type.in_(source_types))

        chunks = list((await self.session.execute(stmt)).scalars().all())
        if not chunks:
            return []

        query = np.asarray(query_embedding, dtype=np.float64)
        matrix = np.asarray([chunk.embedding for chunk in chunks], dtype=np.float64)
        scores = cosine_similarity(query, matrix)

        ranked = sorted(zip(chunks, scores, strict=True), key=lambda p: p[1], reverse=True)
        return [
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                document_title=chunk.document_title,
                source_type=chunk.source_type,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                score=float(score),
            )
            for chunk, score in ranked[:top_k]
        ]


class ChromaVectorStore(VectorStore):
    """ChromaDB-backed search.

    Kept deliberately thin: it queries an existing Chroma collection that the
    knowledge-base service populates in lockstep with the database rows, so the
    ``document_chunks`` table stays the system of record either way. ChromaDB
    is imported lazily so it remains an optional dependency.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._collection = None

    def _get_collection(self):  # type: ignore[no-untyped-def]
        if self._collection is not None:
            return self._collection
        try:
            import chromadb
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "VECTOR_STORE=chroma but chromadb is not installed. "
                "Install it, or use VECTOR_STORE=database."
            ) from exc
        client = chromadb.HttpClient(
            host=self.settings.CHROMA_HOST, port=self.settings.CHROMA_PORT
        )
        self._collection = client.get_or_create_collection(self.settings.CHROMA_COLLECTION)
        return self._collection

    async def search(
        self,
        query_embedding: list[float],
        *,
        top_k: int,
        embedding_model: str,
        source_types: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        where: dict[str, object] = {"embedding_model": embedding_model}
        if source_types:
            where["source_type"] = {"$in": source_types}

        collection = self._get_collection()
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        ids = (result.get("ids") or [[]])[0]

        chunks: list[RetrievedChunk] = []
        for chunk_id, content, meta, distance in zip(
            ids, documents, metadatas, distances, strict=False
        ):
            meta = meta or {}
            chunks.append(
                RetrievedChunk(
                    chunk_id=uuid.UUID(str(chunk_id)),
                    document_id=uuid.UUID(str(meta.get("document_id"))),
                    document_title=meta.get("document_title"),
                    source_type=meta.get("source_type"),
                    chunk_index=int(meta.get("chunk_index", 0)),
                    content=content,
                    # Chroma returns a cosine *distance*; convert to similarity.
                    score=1.0 - float(distance),
                )
            )
        return chunks


def get_vector_store(session: AsyncSession, settings: Settings) -> VectorStore:
    """Construct the vector store named by ``VECTOR_STORE``."""
    if settings.VECTOR_STORE == "chroma":
        return ChromaVectorStore(settings)
    return DatabaseVectorStore(session)
