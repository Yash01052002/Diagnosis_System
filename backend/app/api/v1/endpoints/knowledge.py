"""Knowledge-base (document) endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from app.api.deps import (
    AdminUser,
    EngineerUser,
    KnowledgeBaseServiceDep,
    PaginationDep,
    RequestContextDep,
    SettingsDep,
    require_engineer,
    require_viewer,
)
from app.core.exceptions import ValidationError
from app.models.document import DocumentSourceType, DocumentStatus
from app.schemas.common import ErrorResponse, Page
from app.schemas.knowledge import (
    DocumentCreate,
    DocumentRead,
    KnowledgeBaseStats,
    RetrievedChunkRead,
    SearchRequest,
    SearchResponse,
)

router = APIRouter(prefix="/knowledge-base", tags=["Knowledge Base"])

#: Uploaded documents are decoded as text; a firmware knowledge base is manuals,
#: notes and troubleshooting guides, not binaries.
MAX_INLINE_UPLOAD = 32 * 1024 * 1024


@router.get(
    "/documents",
    response_model=Page[DocumentRead],
    dependencies=[Depends(require_viewer)],
    summary="List knowledge-base documents",
)
async def list_documents(
    service: KnowledgeBaseServiceDep,
    pagination: PaginationDep,
    q: Annotated[str | None, Query(description="Search title or filename")] = None,
    source_type: Annotated[
        DocumentSourceType | None, Query(description="Filter by document category")
    ] = None,
    status_filter: Annotated[
        DocumentStatus | None, Query(alias="status", description="Filter by index status")
    ] = None,
) -> Page[DocumentRead]:
    """Paginated list of the reference corpus."""
    items, total = await service.search(
        query=q,
        source_type=source_type,
        status=status_filter,
        offset=pagination.offset,
        limit=pagination.limit,
    )
    return Page.create([DocumentRead.model_validate(item) for item in items], total, pagination)


@router.get(
    "/stats",
    response_model=KnowledgeBaseStats,
    dependencies=[Depends(require_viewer)],
    summary="Knowledge-base overview",
)
async def knowledge_base_stats(
    service: KnowledgeBaseServiceDep, settings: SettingsDep
) -> KnowledgeBaseStats:
    """Document and chunk totals, plus the active providers."""
    stats = await service.stats()
    return KnowledgeBaseStats(
        documents=stats["documents"],
        chunks=stats["chunks"],
        embedding_provider=settings.EMBEDDING_PROVIDER,
        vector_store=settings.VECTOR_STORE,
    )


@router.post(
    "/documents",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a document from text",
    responses={
        409: {"model": ErrorResponse, "description": "Identical content already indexed"},
        422: {"model": ErrorResponse, "description": "Empty or oversized content"},
    },
)
async def create_document(
    payload: DocumentCreate,
    engineer: EngineerUser,
    service: KnowledgeBaseServiceDep,
    ctx: RequestContextDep,
) -> DocumentRead:
    """Ingest a document from pasted text: chunk, embed and index it."""
    document = await service.ingest(
        title=payload.title,
        content=payload.content,
        source_type=payload.source_type,
        metadata=payload.metadata,
        actor=engineer,
        ctx=ctx,
    )
    return DocumentRead.model_validate(document)


@router.post(
    "/documents/upload",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a text document",
    responses={
        409: {"model": ErrorResponse, "description": "Identical content already indexed"},
        422: {"model": ErrorResponse, "description": "Not decodable as text, or too large"},
    },
)
async def upload_document(
    engineer: EngineerUser,
    service: KnowledgeBaseServiceDep,
    ctx: RequestContextDep,
    file: Annotated[UploadFile, File(description="A UTF-8 text/markdown file")],
    title: Annotated[str | None, Form(description="Defaults to the filename")] = None,
    source_type: Annotated[DocumentSourceType, Form()] = DocumentSourceType.OTHER,
) -> DocumentRead:
    """Upload a `.txt`/`.md` file into the knowledge base.

    PDFs and other binary manuals should be converted to text before upload;
    the platform indexes text, and keeping extraction out of the request path
    avoids a heavy, failure-prone dependency in the API.
    """
    raw = await file.read()
    if len(raw) > MAX_INLINE_UPLOAD:
        raise ValidationError("File is too large.")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(
            "File is not valid UTF-8 text. Convert binary manuals (PDF, etc.) "
            "to text before uploading."
        ) from exc

    document = await service.ingest(
        title=(title or file.filename or "document").strip(),
        content=content,
        source_type=source_type,
        original_filename=file.filename,
        content_type=file.content_type or "text/plain",
        actor=engineer,
        ctx=ctx,
    )
    return DocumentRead.model_validate(document)


@router.get(
    "/documents/{document_id}",
    response_model=DocumentRead,
    dependencies=[Depends(require_viewer)],
    summary="Get a document",
    responses={404: {"model": ErrorResponse, "description": "Document not found"}},
)
async def get_document(
    document_id: uuid.UUID, service: KnowledgeBaseServiceDep
) -> DocumentRead:
    """Document metadata and index status (not the full text)."""
    return DocumentRead.model_validate(await service.get(document_id))


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document",
    responses={404: {"model": ErrorResponse, "description": "Document not found"}},
)
async def delete_document(
    document_id: uuid.UUID,
    admin: AdminUser,
    service: KnowledgeBaseServiceDep,
    ctx: RequestContextDep,
) -> None:
    """Delete a document and all of its chunks (and their vectors)."""
    await service.delete(document_id, actor=admin, ctx=ctx)


@router.post(
    "/search",
    response_model=SearchResponse,
    dependencies=[Depends(require_engineer)],
    summary="Semantic search over the knowledge base",
)
async def search_knowledge_base(
    payload: SearchRequest,
    service: KnowledgeBaseServiceDep,
) -> SearchResponse:
    """Retrieve the passages most relevant to a free-text query.

    Returns only passages above the relevance floor; an empty result means the
    corpus has nothing pertinent, which is a meaningful answer in itself.
    """
    source_types = [str(s) for s in payload.source_types] if payload.source_types else None
    hits = await service.retrieve(
        payload.query, top_k=payload.top_k, source_types=source_types
    )
    return SearchResponse(
        query=payload.query,
        results=[
            RetrievedChunkRead(
                document_id=hit.document_id,
                document_title=hit.document_title,
                source_type=hit.source_type,
                chunk_index=hit.chunk_index,
                score=round(hit.score, 4),
                content=hit.content,
            )
            for hit in hits
        ],
        empty=not hits,
    )
