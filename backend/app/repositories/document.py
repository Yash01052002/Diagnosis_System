"""Document and chunk repositories."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, or_, select

from app.models.document import Document, DocumentChunk
from app.repositories.base import BaseRepository, affected_rows


class DocumentRepository(BaseRepository[Document]):
    model = Document

    async def get_by_hash(self, content_hash: str) -> Document | None:
        stmt = select(Document).where(Document.content_hash == content_hash).limit(1)
        return (await self.session.execute(stmt)).scalars().first()

    async def search(
        self,
        *,
        query: str | None = None,
        source_type: str | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[Document], int]:
        conditions = []
        if source_type:
            conditions.append(Document.source_type == source_type)
        if status:
            conditions.append(Document.status == status)
        if query:
            pattern = f"%{query.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(Document.title).like(pattern),
                    func.lower(func.coalesce(Document.original_filename, "")).like(pattern),
                )
            )

        stmt = select(Document)
        count_stmt = select(func.count()).select_from(Document)
        if conditions:
            stmt = stmt.where(*conditions)
            count_stmt = count_stmt.where(*conditions)

        total = int((await self.session.execute(count_stmt)).scalar_one())
        stmt = stmt.order_by(Document.created_at.desc()).offset(offset).limit(limit)
        items = (await self.session.execute(stmt)).scalars().unique().all()
        return items, total

    async def stats(self) -> dict[str, int]:
        """Corpus totals for the knowledge-base overview."""
        documents = int(
            (await self.session.execute(select(func.count()).select_from(Document))).scalar_one()
        )
        chunks = int(
            (
                await self.session.execute(select(func.count()).select_from(DocumentChunk))
            ).scalar_one()
        )
        return {"documents": documents, "chunks": chunks}


class DocumentChunkRepository(BaseRepository[DocumentChunk]):
    model = DocumentChunk

    async def bulk_insert(self, chunks: Sequence[DocumentChunk]) -> int:
        """Persist a document's chunks. The caller owns the transaction."""
        if not chunks:
            return 0
        self.session.add_all(list(chunks))
        await self.session.flush()
        return len(chunks)

    async def delete_for_document(self, document_id: uuid.UUID) -> int:
        stmt = delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        return affected_rows(await self.session.execute(stmt))

    async def count_for_document(self, document_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
        )
        return int((await self.session.execute(stmt)).scalar_one())
