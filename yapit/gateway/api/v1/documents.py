import hashlib
import io
import logging
import math
import re
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

import httpx
import pymupdf
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, HttpUrl, StringConstraints
from sqlmodel import select

from yapit.gateway.auth import authenticate
from yapit.gateway.deps import (
    AuthenticatedUser,
    CurrentDoc,
    DbSession,
    DocumentCache,
    DocumentProcessorManagerDep,
    IsAdmin,
    SettingsDep,
    TextSplitterDep,
    get_or_create_user_credits,
)
from yapit.gateway.domain_models import (
    Block,
    CreditTransaction,
    Document,
    DocumentMetadata,
    DocumentProcessor,
    TransactionStatus,
    TransactionType,
)
from yapit.gateway.exceptions import ResourceNotFoundError, ValidationError
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

        credit_cost: int | None = None
        if endpoint == "document":
            credit_cost = await _calculate_document_credit_cost(
                cached_doc, request.processor_slug, request.pages, db, document_processor_manager
            )
        return DocumentPrepareResponse(
            hash=cache_key, metadata=cached_doc.metadata, endpoint=endpoint, credit_cost=credit_cost
        )

    content, content_type = await _download_document(request.url, settings.document_max_download_size)

    page_count, title = _extract_document_info(content, content_type)
    metadata = DocumentMetadata(
        content_type=content_type,
        total_pages=page_count,
        title=title,
        url=str(request.url),
        file_name=request.url.path,
        file_size=len(content),
    )

    endpoint: Literal["website", "document"] = "website" if content_type.lower() == "text/html" else "document"
    cached_doc = CachedDocument(content=content if endpoint == "document" else None, metadata=metadata)
    ttl = settings.document_cache_ttl_webpage if endpoint == "website" else settings.document_cache_ttl_document
    await cache.store(cache_key, cached_doc.model_dump_json().encode(), ttl_seconds=ttl)

    credit_cost = None
    if endpoint == "document":
        if request.pages:
            invalid_pages = [p for p in request.pages if p < 1 or p > page_count]
            if invalid_pages:
                raise HTTPException(400, f"Invalid page numbers: {invalid_pages}. Document has {page_count} pages.")

        credit_cost = await _calculate_document_credit_cost(
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

        credit_cost = await _calculate_document_credit_cost(
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
    await cache.store(cache_key, cached_doc.model_dump_json().encode(), ttl_seconds=600)

    credit_cost = await _calculate_document_credit_cost(
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

    # TODO: Implement proper XML generation for structured content
    structured_content = req.content  # Placeholder until XML generation is implemented

    doc = await _create_document_with_blocks(
        db=db,
        user_id=user.id,
        content_type="text/plain",
        title=req.title,
        original_text=req.content,
        filtered_text=None,  # No filtering for direct text input
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
    )
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

    # TODO: Implement proper XML generation from markdown
    structured_content = extracted_text  # Placeholder until XML generation is implemented

    doc = await _create_document_with_blocks(
        db=db,
        user_id=user.id,
        content_type=cached_doc.metadata.content_type,
        title=cached_doc.metadata.title or req.title,
        original_text=extracted_text,
        filtered_text=None,  # TODO: Implement filtering
        structured_content=structured_content,
        metadata=cached_doc.metadata,
        extraction_method=extraction_result.extraction_method,
        text_blocks=text_blocks,
    )
    return DocumentCreateResponse(id=doc.id, title=doc.title)


@router.post("/document", response_model=DocumentCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_document(
    req: DocumentCreateRequest,
    db: DbSession,
    cache: DocumentCache,
    user: AuthenticatedUser,
    is_admin: IsAdmin,
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
    if req.pages:
        invalid_pages = [p for p in req.pages if p < 1 or p > cached_doc.metadata.total_pages]
        if invalid_pages:
            raise HTTPException(
                400, f"Invalid page numbers: {invalid_pages}. Document has {cached_doc.metadata.total_pages} pages."
            )

    processor = document_processor_manager.get_processor(req.processor_slug)
    if not processor:
        raise HTTPException(404, rf"Processor {req.processor_slug} not found")

    # Admin auto top-up for development/self-hosting
    if is_admin:
        user_credits = await get_or_create_user_credits(user.id, db)
        if user_credits.balance < 1000:
            top_up_amount = 10000
            balance_before = user_credits.balance
            user_credits.balance += top_up_amount

            transaction = CreditTransaction(
                user_id=user.id,
                type=TransactionType.credit_bonus,
                status=TransactionStatus.completed,
                amount=top_up_amount,
                balance_before=balance_before,
                balance_after=user_credits.balance,
                description="Admin auto top-up for document processing",
            )
            db.add(transaction)
            await db.commit()

    extraction_result = await processor.process_with_billing(
        user_id=user.id,
        cache_key=req.hash,
        db=db,
        cache=cache,
        url=cached_doc.metadata.url,
        content=cached_doc.content,
        content_type=cached_doc.metadata.content_type,
        pages=req.pages,
    )

    extracted_text: str = "\n\n".join(page.markdown for page in extraction_result.pages.values())

    # TODO use md-aware parser to get blocks + structured content
    text_blocks = splitter.split(text=extracted_text)

    # TODO: Implement proper XML generation from markdown
    structured_content = extracted_text  # Placeholder until XML generation is implemented

    doc = await _create_document_with_blocks(
        db=db,
        user_id=user.id,
        content_type=cached_doc.metadata.content_type,
        title=cached_doc.metadata.title or req.title,
        original_text=extracted_text,
        filtered_text=None,  # TODO: Implement filtering
        structured_content=structured_content,
        metadata=cached_doc.metadata,
        extraction_method=extraction_result.extraction_method,
        text_blocks=text_blocks,
    )
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
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        try:
            head_response = await client.head(str(url))
            if head_response.status_code != 200:
                log.debug(f"HEAD request failed with {head_response.status_code}, falling back to GET")
            else:
                content_length = head_response.headers.get("content-length")
                if content_length and int(content_length) > max_size:
                    raise ValidationError(
                        f"File too large: {int(content_length)} bytes exceeds maximum of {max_size} bytes"
                    )
            response = await client.get(str(url))
            response.raise_for_status()
            content = io.BytesIO()
            downloaded = 0
            async for chunk in response.aiter_bytes(chunk_size=8192):
                downloaded += len(chunk)
                if downloaded > max_size:
                    raise ValidationError(
                        f"File too large: downloaded {downloaded} bytes exceeds maximum of {max_size} bytes"
                    )
                content.write(chunk)
            content_type = response.headers.get("content-type", "application/octet-stream")
            return content.getvalue(), content_type
        except httpx.HTTPStatusError as e:
            raise ValidationError(f"Failed to download document: HTTP {e.response.status_code}")
        except httpx.RequestError as e:
            raise ValidationError(f"Failed to download document: {str(e)}")


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
    elif content_type.lower() == "text/html":
        total_pages = 1
        html_text = content.decode("utf-8", errors="ignore")
        title_match = re.search(r"<title[^>]*>([^<]+)</title>", html_text, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()
        else:
            log.warning(f"Failed to extract title from HTML content:\n{html_text}", exc_info=True)
    elif content_type.lower().startswith("text/") or content_type.lower() in [
        "application/xml",
        "application/rss+xml",
        "application/atom+xml",
    ]:
        # Generic text-based formats
        total_pages = 1
    else:
        raise ValidationError(f"Unsupported content type for metadata extraction: {content_type}")

    return total_pages, title


async def _calculate_document_credit_cost(
    cached_doc: CachedDocument,
    processor_slug: str | None,
    pages: list[int] | None,
    db: DbSession,
    document_processor_manager: DocumentProcessorManagerDep,
) -> Decimal | None:
    if not processor_slug:
        return None

    processor_slug = processor_slug or "markitdown"  # TODO better way to handle default processor
    processor = document_processor_manager.get_processor(processor_slug)
    if not processor:
        raise ResourceNotFoundError(f"Document processor '{processor_slug}' not found")

    result = await db.exec(select(DocumentProcessor).where(DocumentProcessor.slug == processor_slug))
    processor_model = result.first()
    if not processor_model:
        raise ResourceNotFoundError(f"Document processor '{processor_slug}' not found in database")

    return calculate_credit_cost(
        cached_doc, processor_credits_per_page=processor_model.credits_per_page, requested_pages=pages
    )


async def _create_document_with_blocks(
    db: DbSession,
    user_id: str,
    content_type: str,
    title: str | None,
    original_text: str,
    filtered_text: str | None,
    structured_content: str,
    metadata: DocumentMetadata,
    extraction_method: str | None,
    text_blocks: list[str],
) -> Document:
    doc = Document(
        user_id=user_id,
        content_type=content_type,
        title=title,
        original_text=original_text,
        filtered_text=filtered_text,
        extraction_method=extraction_method,
        structured_content=structured_content,
        metadata_=metadata,
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


def _estimate_duration_ms(text: str, speed: float = 1.0, chars_per_second: float = 20) -> int:
    """Estimate audio duration in milliseconds. # TODO ... per model/voice est.?

    Args:
        text (str): Text to be synthesized.
        speed (float): TTS speed multiplier (1.0 = normal).
        chars_per_second (float): Baseline CPS estimate at speed=1.0.
    """
    cps = chars_per_second * speed
    return math.ceil(len(text) / cps * 1000)
