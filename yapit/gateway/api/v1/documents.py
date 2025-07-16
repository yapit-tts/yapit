import hashlib
import logging
import math
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, HttpUrl, constr
from sqlmodel import select

from yapit.gateway.auth import authenticate
from yapit.gateway.deps import (
    AuthenticatedUser,
    CurrentDoc,
    DbSession,
    DocumentCache,
    DocumentProcessorManagerDep,
    SettingsDep,
    TextSplitterDep,
)
from yapit.gateway.domain_models import Block, Document, DocumentMetadata, DocumentProcessor
from yapit.gateway.processors.document.base import (
    CachedDocument,
    DocumentExtractionResult,
    ExtractedPage,
    calculate_credit_cost,
)

router = APIRouter(prefix="/v1/documents", tags=["Documents"], dependencies=[Depends(authenticate)])
log = logging.getLogger(__name__)


class DocumentPrepareRequest(BaseModel):
    """Request to prepare a document from URL.

    Args:
        url (HttpUrl): URL of the document to prepare.
        processor_slug (str | None): Which document processor to use (if using ocr, for credit cost calculation).
        pages (list[int] | None): Specific pages to process for credit cost calculation (None means all).
    """

    url: HttpUrl
    processor_slug: str | None = None
    pages: list[int] | None = None


class DocumentPrepareResponse(BaseModel):
    """Response with document metadata and processing costs.

    Args:
        hash: SHA256 hash of the document content (for uploads) or url (for urls), used as cache key
        endpoint: Which API endpoint the client should use to create the document
        credit_cost: Estimated credit cost for processing uncached pages (None for websites/text and non-ocr processing)
    """

    hash: str
    metadata: DocumentMetadata
    endpoint: Literal["text", "website", "document"]
    credit_cost: Decimal | None = None


class BaseDocumentCreateRequest(BaseModel):
    """Base request for document creation.

    Args:
        title (str | None): Optional title for the document.
    """

    title: str | None = None


class TextDocumentCreateRequest(BaseDocumentCreateRequest):
    """Create document from direct text input."""

    content: str = constr(min_length=1, strip_whitespace=True)


class BasePreparedDocumentCreateRequest(BaseDocumentCreateRequest):
    """Base request for creating a document from actual documents that need to obtain a hash from the prepare endpoint first.

    Args:
        hash (str): Unique hash of the prepared document.
    """

    hash: str


class DocumentCreateRequest(BasePreparedDocumentCreateRequest):
    """Create a document from a standard document or image file.

    Args:
        pages (list[int] | None): Specific pages to process (None means all).
        processor_slug (str | None): Slug of the document processor to use (None means default docling processor, non-ocr).
    """

    pages: list[int] | None
    processor_slug: str | None = None


class WebsiteDocumentCreateRequest(BasePreparedDocumentCreateRequest):
    """Create document from a live website."""


class DocumentCreateResponse(BaseModel):
    """Response after document creation."""

    id: UUID
    title: str | None


@router.post("/prepare", response_model=DocumentPrepareResponse)
async def prepare_document(
    request: DocumentPrepareRequest,
    cache: DocumentCache,
    settings: SettingsDep,
    db: DbSession,
    document_processor_manager: DocumentProcessorManagerDep,
) -> DocumentPrepareResponse:
    """Prepare a document from URL for creation."""
    cache_key = hashlib.sha256(str(request.url).encode()).hexdigest()
    cached_data = await cache.retrieve_data(cache_key)
    if cached_data:
        cached_doc = CachedDocument.model_validate_json(cached_data)
        endpoint = "website" if cached_doc.metadata.content_type.lower() == "text/html" else "document"

        credit_cost = None
        if endpoint == "document":
            credit_cost = await calculate_document_credit_cost(
                cached_doc, request.processor_slug, request.pages, db, document_processor_manager
            )
        return DocumentPrepareResponse(
            hash=cache_key, metadata=cached_doc.metadata, endpoint=endpoint, credit_cost=credit_cost
        )
    # TODO: Implement actual HTTP HEAD request to get content-type
    content_type = "text/html"  # Placeholder

    endpoint: Literal["website", "document"] = "website" if content_type.lower() == "text/html" else "document"
    metadata = DocumentMetadata(
        content_type=content_type,
        content_source="url",
        total_pages=1 if endpoint == "website" else 10,  # TODO: Extract actual page count for documents
        file_size_mb=None if endpoint == "website" else 5.0,  # TODO: Get actual file size
        url=str(request.url),
    )

    cached_doc = CachedDocument(metadata=metadata)
    ttl = settings.document_cache_ttl_webpage if endpoint == "website" else settings.document_cache_ttl_document
    await cache.store(cache_key, cached_doc.model_dump_json().encode(), ttl_seconds=ttl)

    credit_cost = None
    if endpoint == "document":
        credit_cost = await calculate_document_credit_cost(
            cached_doc,
            request.processor_slug,
            request.pages,
            db,
            document_processor_manager,
        )
    return DocumentPrepareResponse(hash=cache_key, metadata=metadata, endpoint=endpoint, credit_cost=credit_cost)


@router.post("/prepare/upload", response_model=DocumentPrepareResponse)
async def prepare_document_upload(
    file: UploadFile,
    cache: DocumentCache,
    db: DbSession,
    document_processor_manager: DocumentProcessorManagerDep,
    processor_slug: str | None = None,
    pages: list[int] | None = None,
) -> DocumentPrepareResponse:
    """Prepare a document from file upload."""
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")

    cache_key = hashlib.sha256(content).hexdigest()
    cached_data = await cache.retrieve_data(cache_key)
    if cached_data:
        cached_doc = CachedDocument.model_validate_json(cached_data)

        credit_cost = await calculate_document_credit_cost(
            cached_doc,
            processor_slug,
            pages,
            db,
            document_processor_manager,
        )

        return DocumentPrepareResponse(
            hash=cache_key,
            metadata=cached_doc.metadata,
            endpoint="document",
            credit_cost=credit_cost,
        )

    content_type = file.content_type or "application/octet-stream"

    # Extract metadata
    # TODO: Implement actual metadata extraction
    metadata = DocumentMetadata(
        content_type=content_type,
        content_source="upload",
        total_pages=5,  # TODO: Extract actual page count
        file_size_mb=(file.size or len(content)) / (1024**2),
        filename=file.filename,
    )

    cached_doc = CachedDocument(metadata=metadata, content=content)
    await cache.store(cache_key, cached_doc.model_dump_json().encode(), ttl_seconds=600)

    credit_cost = await calculate_document_credit_cost(
        cached_doc, processor_slug, pages, db, document_processor_manager
    )

    return DocumentPrepareResponse(hash=cache_key, metadata=metadata, endpoint="document", credit_cost=credit_cost)


@router.post("/text", response_model=DocumentCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_text_document(
    req: TextDocumentCreateRequest,
    db: DbSession,
    user: AuthenticatedUser,
    plaintext_splitter: TextSplitterDep,
) -> DocumentCreateResponse:
    """Create a document from direct text input."""
    text_blocks = plaintext_splitter.split(text=req.content)

    doc = Document(
        user_id=user.id,
        content_type="text/plain",
        title=req.title,
        original_text=req.content,
        filtered_text=None,
        metadata_=DocumentMetadata(
            content_type="text/plain",
            content_source="text",
            total_pages=1,
        ),
    )
    db.add(doc)

    blocks = [
        Block(
            document=doc,
            idx=idx,
            text=block_text,
            est_duration_ms=estimate_duration_ms(block_text),
        )
        for idx, block_text in enumerate(text_blocks)
    ]
    db.add_all(blocks)
    await db.commit()
    return DocumentCreateResponse(id=doc.id, title=doc.title)


@router.post("/website", response_model=DocumentCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_website_document(
    req: WebsiteDocumentCreateRequest,
    db: DbSession,
    cache: DocumentCache,
    settings: SettingsDep,
    user: AuthenticatedUser,
    splitter: TextSplitterDep,
) -> DocumentCreateResponse:
    """Create a document from a live website."""
    cached_data = await cache.retrieve_data(req.hash)
    if not cached_data:
        raise HTTPException(
            404,
            rf"Document with hash {req.hash} not found in cache. Have you called {prepare_document}?",
        )
    cached_doc = CachedDocument.model_validate_json(cached_data)
    if cached_doc.metadata.content_type.lower() != "text/html":
        raise HTTPException(400, rf"This endpoint is for websites only. Use {create_document} for files.")

    # TODO: Implement web parser
    # TODO: Web parser should call docling processor (not implemented yet) to convert html to markdown
    extraction_result = DocumentExtractionResult(
        pages={1: ExtractedPage(markdown="# Placeholder\n\nWeb parsing not implemented yet.")},
        extraction_method="web-parser",
    )

    cached_doc.extraction = extraction_result
    await cache.store(
        req.hash,
        cached_doc.model_dump_json().encode(),
        ttl_seconds=settings.document_cache_ttl_webpage,
    )

    extracted_text = extraction_result.pages[1].markdown  # website are just a single page

    # TODO use md-aware parser to get blocks + structured content
    text_blocks = splitter.split(text=extracted_text)

    doc = Document(
        user_id=user.id,
        content_type=cached_doc.metadata.content_type,
        title=cached_doc.metadata.title or req.title,
        source_ref=cached_doc.metadata.url,
        original_text=extracted_text,
        filtered_text=extracted_text,  # TODO: Implement filtering
        extraction_method=extraction_result.extraction_method,
        structured_content=extracted_text,  # TODO: Generate XML with structure
        metadata_=cached_doc.metadata,
    )
    db.add(doc)

    blocks = [
        Block(
            document=doc,
            idx=idx,
            text=block_text,
            est_duration_ms=estimate_duration_ms(block_text),
        )
        for idx, block_text in enumerate(text_blocks)
    ]
    db.add_all(blocks)
    await db.commit()

    return DocumentCreateResponse(id=doc.id, title=doc.title)


@router.post("/document", response_model=DocumentCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_document(
    req: DocumentCreateRequest,
    db: DbSession,
    cache: DocumentCache,
    user: AuthenticatedUser,
    splitter: TextSplitterDep,
    document_processor_manager: DocumentProcessorManagerDep,
) -> DocumentCreateResponse:
    """Create a document from a file (PDF, image, etc)."""
    cached_data = await cache.retrieve_data(req.hash)
    if not cached_data:
        raise HTTPException(
            404,
            rf"Document with hash {req.hash} not found in cache. Have you called {prepare_document} or {prepare_document_upload}?",
        )
    cached_doc = CachedDocument.model_validate_json(cached_data)

    if cached_doc.metadata.content_type.lower() == "text/html":
        raise HTTPException(400, "This endpoint is for documents only. Use /documents/website for websites.")

    processor = document_processor_manager.get_processor(req.processor_slug)
    if not processor:
        raise HTTPException(404, rf"Processor {req.processor_slug} not found")

    extraction_result = await processor.process_with_billing(
        user_id=user.id,
        cache_key=req.hash,
        db=db,
        cache=cache,
        url=cached_doc.metadata.url if cached_doc.metadata.content_source == "url" else None,
        content=cached_doc.content if cached_doc.metadata.content_source == "upload" else None,
        content_type=cached_doc.metadata.content_type,
        pages=req.pages,
    )

    extracted_text: str = "\n\n".join(page.markdown for page in extraction_result.pages.values())

    # TODO use md-aware parser to get blocks + structured content
    text_blocks = splitter.split(text=extracted_text)

    doc = Document(
        user_id=user.id,
        content_type=cached_doc.metadata.content_type,
        title=cached_doc.metadata.title or req.title,
        source_ref=cached_doc.metadata.url or cached_doc.metadata.filename,
        original_text=extracted_text,
        filtered_text=extracted_text,  # TODO: Implement filtering
        extraction_method=extraction_result.extraction_method,
        structured_content=extracted_text,  # TODO: Generate XML with structure
        metadata_=cached_doc.metadata,
    )
    db.add(doc)

    blocks = [
        Block(
            document=doc,
            idx=idx,
            text=block_text,
            est_duration_ms=estimate_duration_ms(block_text),
        )
        for idx, block_text in enumerate(text_blocks)
    ]
    db.add_all(blocks)
    await db.commit()

    return DocumentCreateResponse(id=doc.id, title=doc.title)


@router.get("/{document_id}")
async def get_document(document: CurrentDoc) -> Document:
    return document


@router.get("/{document_id}/blocks")
async def get_document_blocks(
    document: CurrentDoc,
    db: DbSession,
    offset: int = 0,
    limit: int = Query(default=100, le=100),
) -> list[Block]:
    """Get document blocks."""
    result = await db.exec(
        select(Block).where(Block.document_id == document.id).order_by(Block.idx).offset(offset).limit(limit)
    )
    return result.all()


# TODO raise exceptionsi nstead of returning None if not found
async def calculate_document_credit_cost(
    cached_doc: CachedDocument,
    processor_slug: str | None,
    pages: list[int] | None,
    db: DbSession,
    document_processor_manager: DocumentProcessorManagerDep,
) -> Decimal | None:
    """Calculate credit cost for document processing.

    Returns None if:
    - No processor specified
    - Processor not found
    - Not a document (e.g., website)
    """
    if not processor_slug:
        return None

    processor = document_processor_manager.get_processor(processor_slug)
    if not processor:
        return None

    result = await db.exec(select(DocumentProcessor).where(DocumentProcessor.slug == processor_slug))
    processor_model = result.first()
    if not processor_model:
        return None

    return calculate_credit_cost(
        cached_doc, processor_credits_per_page=processor_model.credits_per_page, requested_pages=pages
    )


def estimate_duration_ms(text: str, speed: float = 1.0, chars_per_second: float = 20) -> int:
    """Estimate audio duration in milliseconds. # TODO ... per model/voice est.?

    Args:
        text (str): Text to be synthesized.
        speed (float): TTS speed multiplier (1.0 = normal).
        chars_per_second (float): Baseline CPS estimate at speed=1.0.
    """
    cps = chars_per_second * speed
    return math.ceil(len(text) / cps * 1000)
