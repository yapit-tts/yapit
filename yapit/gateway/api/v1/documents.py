import datetime as dt
import hashlib
import io
import math
import re
import shutil
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urljoin, urlparse
from uuid import UUID

import httpx
import pymupdf
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from loguru import logger
from markitdown import MarkItDown
from pydantic import BaseModel, Field, HttpUrl, StringConstraints
from sqlmodel import col, select

from yapit.gateway.auth import authenticate
from yapit.gateway.cache import Cache
from yapit.gateway.constants import SUPPORTED_WEB_MIME_TYPES
from yapit.gateway.deps import (
    AiProcessorDep,
    AuthenticatedUser,
    CurrentDoc,
    DbSession,
    DocumentCache,
    ExtractionCache,
    FreeProcessorDep,
    IsAdmin,
    SettingsDep,
)
from yapit.gateway.document.base import (
    BaseDocumentProcessor,
    CachedDocument,
    DocumentExtractionResult,
    ExtractedPage,
)
from yapit.gateway.document.playwright_renderer import render_with_js
from yapit.gateway.domain_models import Block, Document, DocumentMetadata, UserPreferences
from yapit.gateway.exceptions import ResourceNotFoundError
from yapit.gateway.markdown import parse_markdown, transform_to_document

router = APIRouter(prefix="/v1/documents", tags=["Documents"], dependencies=[Depends(authenticate)])
public_router = APIRouter(prefix="/v1/documents", tags=["Documents"])


class DocumentPrepareRequest(BaseModel):
    """Request to prepare a document from URL.

    Args:
        url (HttpUrl): URL of the document to prepare.
        processor_slug (str | None): Which document processor to use (if using ocr, for credit cost calculation).
    """

    url: HttpUrl
    processor_slug: str | None = None


class DocumentPrepareResponse(BaseModel):
    """Response with document metadata for preparation.

    Args:
        hash: SHA256 hash of the document content (for uploads) or url (for urls), used as cache key
        content_hash: SHA256 hash of actual content (for extraction progress tracking)
        endpoint: Which API endpoint the client should use to create the document
        uncached_pages: Set of page numbers that need OCR processing (empty for websites/text)
    """

    hash: str
    content_hash: str
    metadata: DocumentMetadata
    endpoint: Literal["text", "website", "document"]
    uncached_pages: set[int]


class BaseDocumentCreateRequest(BaseModel):
    """Base request for document creation.

    Args:
        title (str | None): Optional title for the document.
    """

    title: str | None = None


class TextDocumentCreateRequest(BaseDocumentCreateRequest):
    """Create document from direct text input."""

    content: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class BasePreparedDocumentCreateRequest(BaseDocumentCreateRequest):
    """Base request for creating a document from actual documents that need to obtain a hash from the prepare endpoint first.

    Args:
        hash (str): Unique hash of the prepared document.
    """

    hash: str


class DocumentCreateRequest(BasePreparedDocumentCreateRequest):
    """Create a document from a standard document or image file.

    Args:
        pages: List of page indices to process (0-indexed). None = all pages.
        ai_transform: Use AI-powered extraction (requires subscription). False = free markitdown.
    """

    pages: list[int] | None = None
    ai_transform: bool = False


class WebsiteDocumentCreateRequest(BasePreparedDocumentCreateRequest):
    """Create document from a live website."""


class DocumentCreateResponse(BaseModel):
    """Response after document creation."""

    id: UUID
    title: str | None
    failed_pages: list[int] = []  # Pages that failed extraction (0-indexed)


class ExtractionStatusResponse(BaseModel):
    """Progress of an ongoing extraction."""

    total_pages: int
    completed_pages: list[int]
    status: Literal["processing", "complete", "not_found"]


class ExtractionStatusRequest(BaseModel):
    """Request for extraction status check."""

    content_hash: str
    processor_slug: str
    pages: list[int]


@router.post("/extraction/status", response_model=ExtractionStatusResponse)
async def get_extraction_status(
    req: ExtractionStatusRequest,
    extraction_cache: ExtractionCache,
    ai_processor: AiProcessorDep,
    free_processor: FreeProcessorDep,
) -> ExtractionStatusResponse:
    """Get progress of an ongoing document extraction by checking cache directly."""
    processor = ai_processor if req.processor_slug == "gemini" else free_processor
    if not processor or not processor._extraction_key_prefix:
        return ExtractionStatusResponse(total_pages=len(req.pages), completed_pages=[], status="not_found")

    completed = []
    for page_idx in req.pages:
        cache_key = processor._extraction_cache_key(req.content_hash, page_idx)
        if await extraction_cache.exists(cache_key):
            completed.append(page_idx)

    is_complete = len(completed) >= len(req.pages)
    return ExtractionStatusResponse(
        total_pages=len(req.pages),
        completed_pages=completed,
        status="complete" if is_complete else "processing",
    )


@router.post("/prepare", response_model=DocumentPrepareResponse)
async def prepare_document(
    request: DocumentPrepareRequest,
    file_cache: DocumentCache,
    extraction_cache: ExtractionCache,
    settings: SettingsDep,
    ai_processor: AiProcessorDep,
) -> DocumentPrepareResponse:
    """Prepare a document from URL for creation."""
    url_hash = hashlib.sha256(str(request.url).encode()).hexdigest()

    # Check URL cache first (same URL within TTL = no download needed)
    cached_data = await file_cache.retrieve_data(url_hash)
    if cached_data:
        cached_doc = CachedDocument.model_validate_json(cached_data)
        endpoint = _get_endpoint_type_from_content_type(cached_doc.metadata.content_type)
        # Compute content_hash for extraction cache lookup
        content_hash = hashlib.sha256(cached_doc.content).hexdigest() if cached_doc.content else url_hash
        uncached_pages = (
            await _get_uncached_pages(
                content_hash,
                cached_doc.metadata.total_pages,
                extraction_cache,
                ai_processor,
            )
            if _needs_ocr_processing(cached_doc.metadata.content_type)
            else set()
        )
        return DocumentPrepareResponse(
            hash=url_hash,
            content_hash=content_hash,
            metadata=cached_doc.metadata,
            endpoint=endpoint,
            uncached_pages=uncached_pages,
        )

    content, content_type = await _download_document(request.url, settings.document_max_download_size)

    page_count, title = _extract_document_info(content, content_type)
    metadata = DocumentMetadata(
        content_type=content_type,
        total_pages=page_count,
        title=title,
        url=str(request.url),
        file_name=Path(request.url.path).name or None,
        file_size=len(content),
    )

    endpoint = _get_endpoint_type_from_content_type(content_type)
    cached_doc = CachedDocument(content=content, metadata=metadata)
    await file_cache.store(url_hash, cached_doc.model_dump_json().encode())

    content_hash = hashlib.sha256(content).hexdigest()
    uncached_pages = (
        await _get_uncached_pages(
            content_hash,
            metadata.total_pages,
            extraction_cache,
            ai_processor,
        )
        if _needs_ocr_processing(content_type)
        else set()
    )
    return DocumentPrepareResponse(
        hash=url_hash, content_hash=content_hash, metadata=metadata, endpoint=endpoint, uncached_pages=uncached_pages
    )


@router.post("/prepare/upload", response_model=DocumentPrepareResponse)
async def prepare_document_upload(
    file: UploadFile,
    file_cache: DocumentCache,
    extraction_cache: ExtractionCache,
    ai_processor: AiProcessorDep,
) -> DocumentPrepareResponse:
    """Prepare a document from file upload."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Empty file")

    cache_key = hashlib.sha256(content).hexdigest()
    cached_data = await file_cache.retrieve_data(cache_key)
    if cached_data:
        cached_doc = CachedDocument.model_validate_json(cached_data)
        uncached_pages = (
            await _get_uncached_pages(
                cache_key,
                cached_doc.metadata.total_pages,
                extraction_cache,
                ai_processor,
            )
            if _needs_ocr_processing(cached_doc.metadata.content_type)
            else set()
        )
        return DocumentPrepareResponse(
            hash=cache_key,
            content_hash=cache_key,
            metadata=cached_doc.metadata,
            endpoint="document",
            uncached_pages=uncached_pages,
        )

    content_type = file.content_type or "application/octet-stream"

    total_pages, title = _extract_document_info(content, content_type)
    metadata = DocumentMetadata(
        content_type=content_type,
        total_pages=total_pages,
        title=title,
        url=None,
        file_name=file.filename,
        file_size=len(content),
    )

    cached_doc = CachedDocument(metadata=metadata, content=content)
    await file_cache.store(cache_key, cached_doc.model_dump_json().encode())

    uncached_pages = (
        await _get_uncached_pages(
            cache_key,
            metadata.total_pages,
            extraction_cache,
            ai_processor,
        )
        if _needs_ocr_processing(content_type)
        else set()
    )
    return DocumentPrepareResponse(
        hash=cache_key, content_hash=cache_key, metadata=metadata, endpoint="document", uncached_pages=uncached_pages
    )


@router.post("/text", response_model=DocumentCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_text_document(
    req: TextDocumentCreateRequest,
    db: DbSession,
    settings: SettingsDep,
    user: AuthenticatedUser,
) -> DocumentCreateResponse:
    """Create a document from direct text input."""
    prefs = await db.get(UserPreferences, user.id)

    ast = parse_markdown(req.content)
    structured_doc = transform_to_document(
        ast,
        max_block_chars=settings.max_block_chars,
        soft_limit_mult=settings.soft_limit_mult,
        min_chunk_size=settings.min_chunk_size,
    )
    structured_content = structured_doc.model_dump_json()
    text_blocks = structured_doc.get_audio_blocks()

    doc = await _create_document_with_blocks(
        db=db,
        user_id=user.id,
        title=req.title,
        original_text=req.content,
        structured_content=structured_content,
        metadata=DocumentMetadata(
            content_type="text/plain",
            total_pages=1,
            title=None,
            url=None,
            file_name=None,
            file_size=len(req.content.encode("utf-8")),
        ),
        extraction_method=None,
        text_blocks=text_blocks,
        is_public=prefs.default_documents_public if prefs else False,
    )
    return DocumentCreateResponse(id=doc.id, title=doc.title)


@router.post("/website", response_model=DocumentCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_website_document(
    req: WebsiteDocumentCreateRequest,
    db: DbSession,
    file_cache: DocumentCache,
    settings: SettingsDep,
    user: AuthenticatedUser,
) -> DocumentCreateResponse:
    """Create a document from a live website."""
    prefs = await db.get(UserPreferences, user.id)
    cached_data = await file_cache.retrieve_data(req.hash)
    if not cached_data:
        raise ResourceNotFoundError(
            CachedDocument.__name__,
            req.hash,
            message=f"Document with hash {req.hash!r} not found in cache. Have you called /prepare?",
        )
    cached_doc = CachedDocument.model_validate_json(cached_data)
    if _get_endpoint_type_from_content_type(cached_doc.metadata.content_type) != "website":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This endpoint is for websites only. Use /document for files.",
        )

    if not cached_doc.content:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Cached document has no content. This should not happen.",
        )

    md = MarkItDown(enable_plugins=False)
    result = md.convert_stream(io.BytesIO(cached_doc.content))
    markdown = result.markdown

    if cached_doc.metadata.url and _needs_js_rendering(cached_doc.content, markdown):
        logger.info(f"JS rendering detected, using Playwright for {cached_doc.metadata.url}")
        rendered_html = await render_with_js(cached_doc.metadata.url)
        result = md.convert_stream(io.BytesIO(rendered_html.encode("utf-8")))
        markdown = result.markdown

    if cached_doc.metadata.url:
        markdown = _resolve_relative_urls(markdown, cached_doc.metadata.url)
    extraction_result = DocumentExtractionResult(
        pages={0: ExtractedPage(markdown=markdown, images=[])},
        extraction_method="markitdown",
    )

    extracted_text = extraction_result.pages[0].markdown  # website are just a single page

    ast = parse_markdown(extracted_text)
    structured_doc = transform_to_document(
        ast,
        max_block_chars=settings.max_block_chars,
        soft_limit_mult=settings.soft_limit_mult,
        min_chunk_size=settings.min_chunk_size,
    )
    structured_content = structured_doc.model_dump_json()
    text_blocks = structured_doc.get_audio_blocks()

    doc = await _create_document_with_blocks(
        db=db,
        user_id=user.id,
        title=cached_doc.metadata.title or req.title or cached_doc.metadata.file_name,
        original_text=extracted_text,
        structured_content=structured_content,
        metadata=cached_doc.metadata,
        extraction_method=extraction_result.extraction_method,
        text_blocks=text_blocks,
        is_public=prefs.default_documents_public if prefs else False,
    )
    return DocumentCreateResponse(id=doc.id, title=doc.title)


@router.post(
    "/document",
    response_model=DocumentCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_document(
    req: DocumentCreateRequest,
    db: DbSession,
    file_cache: DocumentCache,
    extraction_cache: ExtractionCache,
    settings: SettingsDep,
    user: AuthenticatedUser,
    is_admin: IsAdmin,
    free_processor: FreeProcessorDep,
    ai_processor: AiProcessorDep,
) -> DocumentCreateResponse:
    """Create a document from a file (PDF, image, etc)."""
    prefs = await db.get(UserPreferences, user.id)
    cached_data = await file_cache.retrieve_data(req.hash)
    if not cached_data:
        raise ResourceNotFoundError(
            CachedDocument.__name__,
            req.hash,
            message=f"Document with hash {req.hash!r} not found in cache. Have you called /prepare or /prepare/upload?",
        )
    cached_doc = CachedDocument.model_validate_json(cached_data)

    if _get_endpoint_type_from_content_type(cached_doc.metadata.content_type) == "website":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This endpoint is for documents only. Use /website for websites.",
        )
    _validate_page_numbers(req.pages, cached_doc.metadata.total_pages)

    if req.ai_transform:
        if not ai_processor:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI transform not configured on this server",
            )
        processor = ai_processor
    else:
        processor = free_processor
    if not cached_doc.content:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Cached document has no content",
        )

    content_hash = hashlib.sha256(cached_doc.content).hexdigest()
    extraction_result = await processor.process_with_billing(
        user_id=user.id,
        content_hash=content_hash,
        db=db,
        extraction_cache=extraction_cache,
        content=cached_doc.content,
        content_type=cached_doc.metadata.content_type,
        total_pages=cached_doc.metadata.total_pages,
        file_size=cached_doc.metadata.file_size,
        pages=req.pages,
        is_admin=is_admin,
    )

    # If all pages failed, return error
    if not extraction_result.pages:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Document extraction failed. Please try again later.",
        )

    extracted_text: str = "\n\n".join(page.markdown for page in extraction_result.pages.values())

    ast = parse_markdown(extracted_text)
    structured_doc = transform_to_document(
        ast,
        max_block_chars=settings.max_block_chars,
        soft_limit_mult=settings.soft_limit_mult,
        min_chunk_size=settings.min_chunk_size,
    )
    structured_content = structured_doc.model_dump_json()
    text_blocks = structured_doc.get_audio_blocks()

    doc = await _create_document_with_blocks(
        db=db,
        user_id=user.id,
        title=cached_doc.metadata.title or req.title or cached_doc.metadata.file_name,
        original_text=extracted_text,
        structured_content=structured_content,
        metadata=cached_doc.metadata,
        extraction_method=extraction_result.extraction_method,
        text_blocks=text_blocks,
        is_public=prefs.default_documents_public if prefs else False,
        content_hash=content_hash,
    )
    return DocumentCreateResponse(id=doc.id, title=doc.title, failed_pages=extraction_result.failed_pages)


class DocumentListItem(BaseModel):
    """Minimal document info for list view."""

    id: UUID
    title: str | None
    created: str  # ISO format
    is_public: bool


@router.get("")
async def list_documents(
    db: DbSession,
    user: AuthenticatedUser,
    offset: int = 0,
    limit: int = Query(default=50, le=100),
) -> list[DocumentListItem]:
    """List user's documents, most recent first."""
    result = await db.exec(
        select(Document)
        .where(Document.user_id == user.id)
        .order_by(col(Document.created).desc())
        .offset(offset)
        .limit(limit)
    )
    return [
        DocumentListItem(id=doc.id, title=doc.title, created=doc.created.isoformat(), is_public=doc.is_public)
        for doc in result.all()
    ]


@router.get("/{document_id}")
async def get_document(document: CurrentDoc) -> Document:
    return document


class DocumentUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    is_public: bool | None = Field(default=None)


class DocumentUpdateResponse(BaseModel):
    id: UUID
    title: str | None
    is_public: bool


@router.patch("/{document_id}", response_model=DocumentUpdateResponse)
async def update_document(
    document: CurrentDoc,
    request: DocumentUpdateRequest,
    db: DbSession,
) -> DocumentUpdateResponse:
    """Update document properties."""
    if request.title is not None:
        document.title = request.title
    if request.is_public is not None:
        document.is_public = request.is_public
    await db.commit()
    await db.refresh(document)
    return DocumentUpdateResponse(id=document.id, title=document.title, is_public=document.is_public)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document: CurrentDoc,
    db: DbSession,
    settings: SettingsDep,
) -> None:
    """Delete a document and all its blocks. Cleans up images if last doc with this content."""
    content_hash = document.content_hash

    await db.delete(document)
    await db.commit()

    # Clean up images if no other documents use this content
    if content_hash:
        other_docs = await db.exec(select(Document).where(Document.content_hash == content_hash).limit(1))
        if not other_docs.first():
            images_dir = Path(settings.images_dir) / content_hash
            if images_dir.exists():
                shutil.rmtree(images_dir)


@router.get("/{document_id}/blocks")
async def get_document_blocks(
    document: CurrentDoc,
    db: DbSession,
) -> list[Block]:
    """Get all document blocks for playback.

    Returns all blocks without pagination - needed for playback to work correctly.
    Data size is small (~200 bytes/block), so even 1000+ blocks is fine.
    """
    result = await db.exec(select(Block).where(Block.document_id == document.id).order_by(Block.idx))
    return result.all()


class PositionUpdate(BaseModel):
    block_idx: int


@router.patch("/{document_id}/position")
async def update_position(
    document: CurrentDoc,
    body: PositionUpdate,
    db: DbSession,
) -> dict:
    """Update playback position for cross-device sync."""
    document.last_block_idx = body.block_idx
    document.last_played_at = datetime.now(tz=dt.UTC)
    await db.commit()
    return {"ok": True}


# Public document access (no auth required)


class PublicDocumentResponse(BaseModel):
    """Public document data for viewing shared documents."""

    id: UUID
    title: str | None
    structured_content: str
    original_text: str
    metadata_dict: dict | None
    block_count: int


@public_router.get("/{document_id}/public", response_model=PublicDocumentResponse)
async def get_public_document(
    document_id: UUID,
    db: DbSession,
) -> PublicDocumentResponse:
    """Get a public document without authentication.

    Returns document data if is_public=True, otherwise 404.
    """
    result = await db.exec(select(Document).where(Document.id == document_id, Document.is_public.is_(True)))
    document = result.first()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    block_count = (await db.exec(select(Block).where(Block.document_id == document_id))).all()
    return PublicDocumentResponse(
        id=document.id,
        title=document.title,
        structured_content=document.structured_content,
        original_text=document.original_text,
        metadata_dict=document.metadata_dict,
        block_count=len(block_count),
    )


@public_router.get("/{document_id}/public/blocks")
async def get_public_document_blocks(
    document_id: UUID,
    db: DbSession,
) -> list[Block]:
    """Get blocks for a public document without authentication."""
    result = await db.exec(select(Document).where(Document.id == document_id, Document.is_public.is_(True)))
    document = result.first()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    result = await db.exec(select(Block).where(Block.document_id == document_id).order_by(Block.idx))
    return result.all()


class DocumentImportResponse(BaseModel):
    """Response after importing a public document."""

    id: UUID
    title: str | None


@router.post("/{document_id}/import", response_model=DocumentImportResponse, status_code=status.HTTP_201_CREATED)
async def import_document(
    document_id: UUID,
    db: DbSession,
    user: AuthenticatedUser,
) -> DocumentImportResponse:
    """Import (clone) a public document to the authenticated user's library."""
    result = await db.exec(select(Document).where(Document.id == document_id, Document.is_public.is_(True)))
    source_doc = result.first()
    if not source_doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Clone the document
    new_doc = Document(
        user_id=user.id,
        is_public=False,
        title=source_doc.title,
        original_text=source_doc.original_text,
        extraction_method=source_doc.extraction_method,
        structured_content=source_doc.structured_content,
        metadata_dict=source_doc.metadata_dict,
    )
    db.add(new_doc)

    # Clone the blocks
    source_blocks = await db.exec(select(Block).where(Block.document_id == document_id).order_by(Block.idx))
    db.add_all(
        [
            Block(
                document=new_doc,
                idx=block.idx,
                text=block.text,
                est_duration_ms=block.est_duration_ms,
            )
            for block in source_blocks.all()
        ]
    )

    await db.commit()
    return DocumentImportResponse(id=new_doc.id, title=new_doc.title)


async def _download_document(url: HttpUrl, max_size: int) -> tuple[bytes, str]:
    """Download a document from URL within size limits.

    Args:
        url: URL to download from
        max_size: Maximum allowed file size in bytes

    Returns:
        tuple of (content bytes, content-type header)

    Raises:
        ValidationError: If download fails or file is too large
    """
    headers = {"User-Agent": "Yapit/1.0 (https://yapit.md; document fetcher)"}
    async with httpx.AsyncClient(
        proxy="http://smokescreen:4750",
        follow_redirects=True,
        timeout=30.0,
        headers=headers,
    ) as client:
        try:
            head_response = await client.head(str(url))
            if head_response.status_code != 200:
                logger.debug(f"HEAD request failed with {head_response.status_code}, falling back to GET")
            else:
                content_length = head_response.headers.get("content-length")
                if content_length and int(content_length) > max_size:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File too large: {int(content_length)} bytes exceeds maximum of {max_size} bytes",
                    )
            response = await client.get(str(url))
            response.raise_for_status()
            content = io.BytesIO()
            downloaded = 0
            async for chunk in response.aiter_bytes(chunk_size=8192):
                downloaded += len(chunk)
                if downloaded > max_size:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File too large: downloaded {downloaded} bytes exceeds maximum of {max_size} bytes",
                    )
                content.write(chunk)
            content_bytes = content.getvalue()
            header_type = response.headers.get("content-type", "application/octet-stream")
            sniffed_type = _sniff_content_type(content_bytes)
            # Trust magic bytes over header if we can detect the type
            content_type = sniffed_type if sniffed_type else header_type
            return content_bytes, content_type
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            detail = _get_http_error_message(code)
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)
        except httpx.RequestError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Unable to reach URL - check it's correct and accessible",
            )


def _extract_document_info(content: bytes, content_type: str) -> tuple[int, str | None]:
    """Extract page count and title from document content.

    Args:
        content: Document content as bytes
        content_type: MIME type of the document

    Returns:
        Tuple of (page_count, title)
    """
    title = None
    if content_type.lower() == "application/pdf":
        with pymupdf.open(stream=content, filetype="pdf") as pdf:
            total_pages = len(pdf)
            if pdf.metadata and pdf.metadata.get("title"):
                title = pdf.metadata["title"]
    elif content_type.lower().startswith("image/"):
        total_pages = 1
    elif _get_endpoint_type_from_content_type(content_type) == "website":
        total_pages = 1
        html_text = content.decode("utf-8", errors="ignore")
        title_match = re.search(r"<title[^>]*>([^<]+)</title>", html_text, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()
        else:
            logger.warning(f"Failed to extract title from HTML content:\n{html_text}")
    elif content_type.lower().startswith("text/"):
        total_pages = 1
    else:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported content type for metadata extraction: {content_type}",
        )

    return total_pages, title


def _get_endpoint_type_from_content_type(content_type: str | None) -> Literal["website", "document"]:
    """Determine if content should be handled as a website or document based on MIME type.

    Returns:
        "website" if content is HTML-like, "document" otherwise
    """
    if not content_type:
        return "document"

    try:
        msg = EmailMessage()
        msg["content-type"] = content_type
        main_type = msg.get_content_type().lower()
        return "website" if main_type in SUPPORTED_WEB_MIME_TYPES else "document"
    except Exception:
        return "document"


def _needs_ocr_processing(content_type: str | None) -> bool:
    """Check if content type requires OCR processing (PDFs, images)."""
    if not content_type:
        return False
    ct = content_type.lower()
    return ct == "application/pdf" or ct.startswith("image/")


async def _get_uncached_pages(
    content_hash: str,
    total_pages: int,
    extraction_cache: Cache,
    processor: BaseDocumentProcessor | None,
) -> set[int]:
    """Query extraction cache to find which pages need processing."""
    if not processor or not processor._extraction_key_prefix:
        return set(range(total_pages))

    uncached = set()
    for page_idx in range(total_pages):
        key = f"{content_hash}:{processor._extraction_key_prefix}:{page_idx}"
        if not await extraction_cache.exists(key):
            uncached.add(page_idx)
    return uncached


async def _create_document_with_blocks(
    db: DbSession,
    user_id: str,
    title: str | None,
    original_text: str,
    structured_content: str,
    metadata: DocumentMetadata,
    extraction_method: str | None,
    text_blocks: list[str],
    is_public: bool,
    content_hash: str | None = None,
) -> Document:
    doc = Document(
        user_id=user_id,
        is_public=is_public,
        title=title,
        original_text=original_text,
        extraction_method=extraction_method,
        content_hash=content_hash,
        structured_content=structured_content,
        metadata_dict=metadata.model_dump(),
    )
    db.add(doc)
    db.add_all(
        [
            Block(
                document=doc,
                idx=idx,
                text=block_text,
                est_duration_ms=_estimate_duration_ms(block_text),
            )
            for idx, block_text in enumerate(text_blocks)
        ]
    )
    await db.commit()
    return doc


def _estimate_duration_ms(text: str, speed: float = 1.0, chars_per_second: float = 13) -> int:
    """Estimate audio duration in milliseconds.

    Args:
        text (str): Text to be synthesized.
        speed (float): TTS speed multiplier (1.0 = normal).
        chars_per_second (float): Baseline CPS estimate at speed=1.0.
            Benchmarked at ~13 CPS for Kokoro on realistic document content.
            Variance is high (~40%) due to content type, so treat as rough estimate.
    """
    cps = chars_per_second * speed
    return math.ceil(len(text) / cps * 1000)


def _validate_page_numbers(pages: list[int] | None, total_pages: int) -> None:
    if not pages:
        return
    invalid_pages = [p for p in pages if p < 0 or p >= total_pages]
    if invalid_pages:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid page numbers: {invalid_pages!r}. Document has {total_pages} pages (0-indexed).",
        )


def _resolve_relative_urls(markdown: str, base_url: str) -> str:
    """Resolve relative URLs in markdown images and links to absolute URLs.

    When converting webpages, MarkItDown preserves URLs as-is. Relative paths
    like `/images/foo.png` would resolve to Yapit's domain when rendered in the browser.
    This function resolves them to absolute URLs using the source webpage's URL.

    Also:
    - Encodes spaces in URLs since markdown parsers don't handle unencoded spaces
    - Converts same-page links (https://site.com/page/#section) to anchor links (#section)
    """
    # Parse base URL to detect same-page anchors
    parsed_base = urlparse(base_url)
    base_without_fragment = f"{parsed_base.scheme}://{parsed_base.netloc}{parsed_base.path}"
    # Normalize: remove trailing slash for comparison
    base_normalized = base_without_fragment.rstrip("/")

    def make_resolver(is_image: bool):
        def resolve(match: re.Match) -> str:
            text, url = match.group(1), match.group(2)
            # Encode spaces in URL - markdown parsers choke on unencoded spaces
            url_encoded = url.replace(" ", "%20")

            if url.startswith(("#", "data:")):
                prefix = "!" if is_image else ""
                return f"{prefix}[{text}]({url_encoded})"

            # Check if it's an absolute URL pointing to same page with fragment
            if url.startswith(("http://", "https://")):
                parsed = urlparse(url)
                url_without_fragment = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
                if url_without_fragment == base_normalized and parsed.fragment:
                    # Same page anchor - convert to just the fragment
                    return f"[{text}](#{parsed.fragment})"
                # Different page - keep as external link
                prefix = "!" if is_image else ""
                return f"{prefix}[{text}]({url_encoded})"

            # Relative URL - resolve against base
            resolved = urljoin(base_url, url_encoded)
            # Check if resolved URL points to same page (for relative anchors like /page/#section)
            parsed_resolved = urlparse(resolved)
            resolved_without_fragment = (
                f"{parsed_resolved.scheme}://{parsed_resolved.netloc}{parsed_resolved.path}".rstrip("/")
            )
            if resolved_without_fragment == base_normalized and parsed_resolved.fragment:
                return f"[{text}](#{parsed_resolved.fragment})"
            prefix = "!" if is_image else ""
            return f"{prefix}[{text}]({resolved})"

        return resolve

    # Images: ![alt](url) - MarkItDown doesn't output titles, so just match to closing paren
    markdown = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", make_resolver(True), markdown)
    # Links: [text](url)
    markdown = re.sub(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)", make_resolver(False), markdown)
    return markdown


def _sniff_content_type(content: bytes) -> str | None:
    """Detect content type from magic bytes. Returns None if unknown."""
    if content.startswith(b"%PDF"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        return "image/gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    # HTML detection (check first 1KB for common patterns)
    head = content[:1024].lstrip()
    if head.startswith(b"<!DOCTYPE") or head.startswith(b"<html") or head.startswith(b"<HTML"):
        return "text/html"
    return None


def _get_http_error_message(status_code: int) -> str:
    """Return a user-friendly error message for HTTP status codes."""
    messages = {
        300: "Document has multiple versions - try a more specific URL",
        301: "Page has moved permanently",
        302: "Page has moved temporarily",
        400: "Invalid request to the website",
        401: "This page requires authentication",
        403: "Access to this page is forbidden",
        404: "Page not found - check the URL",
        407: "URL points to a blocked destination",
        408: "Request timed out - the website took too long to respond",
        410: "This page no longer exists",
        429: "Site is rate limiting requests - try again later",
        451: "Content unavailable for legal reasons",
        500: "The target website is having internal issues - try again later",
        502: "The target website's server is not responding - try again later",
        503: "The target website is temporarily unavailable - try again later",
        504: "The target website took too long to respond - try again later",
    }
    if status_code in messages:
        return messages[status_code]
    if 400 <= status_code < 500:
        return f"Website returned client error (HTTP {status_code})"
    if 500 <= status_code < 600:
        return f"Website returned server error (HTTP {status_code})"
    return f"URL returned unexpected status: HTTP {status_code}"


_JS_RENDERING_PATTERNS = [
    r"marked\.parse",  # marked.js
    r"markdown-it",  # markdown-it
    r"renderMarkdown",  # custom pattern like k-a.in
    r"ReactDOM\.render",  # React (legacy)
    r"createRoot",  # React 18+
    r"createApp\s*\(",  # Vue 3
    r"ng-app",  # Angular
    r"\.mount\s*\(",  # Vue mount
]
_JS_PATTERN_REGEX = re.compile("|".join(_JS_RENDERING_PATTERNS), re.IGNORECASE)


def _needs_js_rendering(html: bytes, markdown: str) -> bool:
    """Detect if a page likely needs JavaScript rendering.

    Uses two heuristics:
    1. Content sniffing: look for known JS rendering patterns in HTML
    2. Size heuristic: large HTML but tiny markdown output suggests JS-loaded content

    Returns True if either heuristic triggers.
    """
    html_str = html.decode("utf-8", errors="ignore")

    # Content sniffing: detect known JS rendering frameworks
    if _JS_PATTERN_REGEX.search(html_str):
        logger.debug("JS rendering pattern detected in HTML")
        return True

    # Size heuristic: big HTML (>5KB) but tiny markdown (<500 chars)
    if len(html) > 5000 and len(markdown) < 500:
        logger.debug(f"Size heuristic triggered: {len(html)} bytes HTML -> {len(markdown)} chars markdown")
        return True

    return False
