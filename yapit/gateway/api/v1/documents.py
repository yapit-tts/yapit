import hashlib
import logging
import math
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
from yapit.gateway.domain_models import Block, Document, DocumentType
from yapit.gateway.processors.document.base import CachedDocument, DocumentExtractionResult, ExtractedPage

router = APIRouter(prefix="/v1/documents", tags=["Documents"], dependencies=[Depends(authenticate)])
log = logging.getLogger(__name__)


class DocumentPrepareRequest(BaseModel):
    """Request to prepare a document from URL."""

    url: HttpUrl


class DocumentPrepareResponse(BaseModel):
    """Response with document metadata and processing costs."""

    hash: str
    type: DocumentType
    title: str | None = None
    metadata: dict  # total_pages, credits_required, file_size_mb # TODO this should use a proper model introduced in processors/document/base.py


class PreparedDocumentCreateRequest(BaseModel):
    """Create document from prepared content."""

    hash: str
    pages: list[int] | None  # None => all pages
    processor_slug: str | None = (
        None  # None => web-parser TODO would make things cleaner if we make a separate endpoint for web-parser... which is possible anways since the client HAS to calll prepare, and thus knows the document type
    )


class TextDocumentCreateRequest(BaseModel):
    """Create document from direct text input."""

    content: str = constr(min_length=1, strip_whitespace=True)
    title: str = "Untitled"


class DocumentCreateResponse(BaseModel):
    """Response after document creation."""

    id: UUID
    type: DocumentType
    title: str
    block_count: int


@router.post("/prepare", response_model=DocumentPrepareResponse)
async def prepare_document(
    request: DocumentPrepareRequest, cache: DocumentCache, settings: SettingsDep
) -> DocumentPrepareResponse:
    """Prepare a document from URL for creation."""
    cache_key = hashlib.sha256(str(request.url).encode()).hexdigest()
    cached_data = await cache.retrieve_data(cache_key)
    if cached_data:
        cached_doc = CachedDocument.model_validate_json(cached_data)
        return DocumentPrepareResponse(
            hash=cache_key,
            type=cached_doc.metadata["document_type"],
            title=cached_doc.metadata.get("title"),
            metadata=cached_doc.metadata,
        )

    # Detect document type
    # TODO: Implement actual HTTP HEAD request to get content-type
    content_type = "text/html"  # Placeholder
    doc_type = detect_document_type(str(request.url), content_type)

    if doc_type == DocumentType.website:
        # For websites, we'll parse immediately (free)
        # TODO: Implement web parser
        #  We'll leave it to the web parser implementation to cache raw webpage html content
        metadata = {
            "document_type": doc_type.value,
            "total_pages": 1,  # always 1 for webpages
            "credits_required": 0,
            "file_size_mb": 0.1,
        }
        # Create cached document with placeholder extraction
        cached_doc = CachedDocument(metadata=metadata)
        ttl = settings.document_cache_ttl_webpage
    else:
        # For documents, extract metadata without downloading full file
        # TODO: Implement PDF metadata extraction with range requests
        metadata = {
            "document_type": doc_type.value,
            "total_pages": 10,  # Placeholder
            "credits_required": 0,  # Will be calculated based on processor
            "file_size_mb": 5.0,  # Placeholder
        }
        cached_doc = CachedDocument(
            metadata=metadata,
            content={"url": str(request.url)},  # Store URL for processors # TODO why not in metadata?
        )
        ttl = settings.document_cache_ttl_document
    await cache.store(cache_key, cached_doc.model_dump_json().encode(), ttl_seconds=ttl)
    return DocumentPrepareResponse(
        hash=cache_key,
        type=doc_type,
        title=metadata.get("title"),
        metadata=metadata,
    )


@router.post("/prepare/upload", response_model=DocumentPrepareResponse)
async def prepare_document_upload(file: UploadFile, cache: DocumentCache) -> DocumentPrepareResponse:
    """Prepare a document from file upload."""
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")

    cache_key = hashlib.sha256(content).hexdigest()
    cached_data = await cache.retrieve_data(cache_key)
    if cached_data:
        cached_doc = CachedDocument.model_validate_json(cached_data)
        return DocumentPrepareResponse(
            hash=cache_key,
            type=cached_doc.metadata["document_type"],
            title=cached_doc.metadata.get("title", file.filename),
            metadata=cached_doc.metadata,
        )

    doc_type = detect_document_type(file.filename or "", file.content_type or "")  # TODO unused variable

    # Extract metadata
    # TODO: Implement actual metadata extraction
    metadata = {
        "document_type": DocumentType.document.value,  # Uploads are always documents
        "total_pages": 5,  # Placeholder
        "credits_required": 0,  # Will be calculated based on processor
        "file_size_mb": file.size or len(content) / (1024**2),
        "filename": file.filename,
    }

    cached_doc = CachedDocument(
        metadata=metadata,
        content={  # Cache document with content (brief TTL for uploads)
            "data": content.hex(),  # Store as hex for JSON serialization # TODO why not base64?
            "content_type": file.content_type or "application/octet-stream",
        },
    )
    await cache.store(cache_key, cached_doc.model_dump_json().encode(), ttl_seconds=600)
    return DocumentPrepareResponse(hash=cache_key, type=DocumentType.document, title=file.filename, metadata=metadata)


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
        type=DocumentType.text,
        title=req.title,
        original_text=req.content,
        filtered_text=None,
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
    return DocumentCreateResponse(
        id=doc.id,
        type=doc.type,
        title=doc.title,
        block_count=len(blocks),
    )


@router.post("", response_model=DocumentCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_document(
    req: PreparedDocumentCreateRequest,
    db: DbSession,
    cache: DocumentCache,
    settings: SettingsDep,
    user: AuthenticatedUser,
    splitter: TextSplitterDep,
    document_processor_manager: DocumentProcessorManagerDep,
) -> DocumentCreateResponse:
    """Create a document from prepared content."""
    cached_data = await cache.retrieve_data(req.hash)
    if not cached_data:
        raise HTTPException(
            404,
            rf"Document with hash {req.hash} not found in cache. Have you called {prepare_document} or {prepare_document_upload}?",
        )
    cached_doc = CachedDocument.model_validate_json(cached_data)

    doc_type = DocumentType(cached_doc.metadata["document_type"])
    if doc_type == DocumentType.website:
        # TODO: Implement web parser
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
    else:
        processor = document_processor_manager.get_processor(req.processor_slug)
        if not processor:
            raise HTTPException(404, rf"Processor {req.processor_slug} not found")
        extraction_result = await processor.process_with_billing(
            # content=, # TODO... pass both url and content (one of which can/should be None)
            content_type=...,  # TODO, need to pass the detected content type from prepare_document here... at least for mistral, this needs to at least differentiate between Image files (JPG, PNG, etc.) vs any document format that's not a simple image (pdf, ...)
            user_id=user.id,
            cache_key=req.hash,
            db=db,
            cache=cache,
            pages=req.pages,
        )
    extracted_text: str = "\n\n".join(page.markdown for page in extraction_result.pages.values())

    # TODO use md-aware parser to get blocks + structured content
    text_blocks = splitter.split(text=extracted_text)

    doc = Document(
        user_id=user.id,
        type=doc_type,
        title=cached_doc.metadata.get("title", "Untitled"),
        source_ref=cached_doc.metadata.get("url") or cached_doc.metadata.get("filename"),
        original_text=extracted_text,
        filtered_text=extracted_text,  # TODO: Implement filtering
        extraction_method=extraction_result.extraction_method,
        structured_content=extracted_text,  # TODO: Generate XML with structure
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

    return DocumentCreateResponse(
        id=doc.id,
        type=doc.type,
        title=doc.title,
        block_count=len(blocks),
    )


@router.get("/{document_id}")
async def get_document(document: CurrentDoc) -> Document:
    """Get document metadata."""
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


def estimate_duration_ms(text: str, speed: float = 1.0, chars_per_second: float = 20) -> int:
    """Estimate audio duration in milliseconds. # TODO ... per model/voice est.?

    Args:
        text (str): Text to be synthesized.
        speed (float): TTS speed multiplier (1.0 = normal).
        chars_per_second (float): Baseline CPS estimate at speed=1.0.
    """
    cps = chars_per_second * speed
    return math.ceil(len(text) / cps * 1000)


def detect_document_type(url: str, content_type: str | None = None) -> DocumentType:
    """Detect if URL points to a document or website. # TODO do this properly with HTTP HEAD request to get content-type header or whatever is needed

    Args:
        url: The URL to check
        content_type: Optional Content-Type header from HTTP response

    Returns:
        DocumentType.document or DocumentType.website (defaults to website if unsure)
    """
    url_lower = url.lower()

    # Check URL patterns for documents
    doc_extensions = (".pdf", ".docx", ".doc", ".pptx", ".ppt", ".png", ".jpg", ".jpeg", ".tiff")
    if any(url_lower.endswith(ext) for ext in doc_extensions):
        return DocumentType.document

    # todo: for e.g. arxiv we could replace /abs/ with /pdf/ automatically (not /html/ bcs not every paper has it)

    # Check Content-Type header
    if content_type:
        content_type_lower = content_type.lower()

        # Document MIME types
        doc_types = ("application/pdf", "image/", "application/msword", "application/vnd.openxmlformats-officedocument")
        if any(doc_type in content_type_lower for doc_type in doc_types):
            return DocumentType.document

        # Website MIME types
        if "text/html" in content_type_lower:
            return DocumentType.website

    # Default to website for all unclear cases
    return DocumentType.website
