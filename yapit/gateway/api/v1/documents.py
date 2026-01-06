import datetime as dt
import hashlib
import io
import math
import re
from datetime import datetime
from email.message import EmailMessage
from typing import Annotated, Literal
from urllib.parse import urljoin, urlparse
from uuid import UUID

import httpx
import pymupdf
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from loguru import logger
from markitdown import MarkItDown
from pydantic import BaseModel, HttpUrl, StringConstraints
from sqlmodel import col, select

from yapit.gateway.auth import authenticate
from yapit.gateway.constants import SUPPORTED_WEB_MIME_TYPES
from yapit.gateway.deps import (
    AuthenticatedUser,
    CurrentDoc,
    DbSession,
    DocumentCache,
    DocumentProcessorManagerDep,
    IsAdmin,
    SettingsDep,
)
from yapit.gateway.domain_models import Block, Document, DocumentMetadata, DocumentProcessor
from yapit.gateway.exceptions import ResourceNotFoundError
from yapit.gateway.processors.document.base import (
    CachedDocument,
    DocumentExtractionResult,
    ExtractedPage,
    get_uncached_pages,
)
from yapit.gateway.processors.markdown import parse_markdown, transform_to_document

router = APIRouter(prefix="/v1/documents", tags=["Documents"], dependencies=[Depends(authenticate)])


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
        endpoint: Which API endpoint the client should use to create the document
        uncached_pages: Set of page numbers that need OCR processing (empty for websites/text)
    """

    hash: str
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
) -> DocumentPrepareResponse:
    """Prepare a document from URL for creation."""
    cache_key = hashlib.sha256(str(request.url).encode()).hexdigest()
    cached_data = await cache.retrieve_data(cache_key)
    if cached_data:
        cached_doc = CachedDocument.model_validate_json(cached_data)
        endpoint = _get_endpoint_type_from_content_type(cached_doc.metadata.content_type)
        uncached_pages = (
            get_uncached_pages(cached_doc, None) if _needs_ocr_processing(cached_doc.metadata.content_type) else set()
        )
        return DocumentPrepareResponse(
            hash=cache_key,
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
        file_name=request.url.path,
        file_size=len(content),
    )

    endpoint = _get_endpoint_type_from_content_type(content_type)
    cached_doc = CachedDocument(content=content, metadata=metadata)
    ttl = settings.document_cache_ttl_webpage if endpoint == "website" else settings.document_cache_ttl_document
    await cache.store(cache_key, cached_doc.model_dump_json().encode(), ttl_seconds=ttl)

    uncached_pages = get_uncached_pages(cached_doc, None) if _needs_ocr_processing(content_type) else set()
    return DocumentPrepareResponse(hash=cache_key, metadata=metadata, endpoint=endpoint, uncached_pages=uncached_pages)


@router.post("/prepare/upload", response_model=DocumentPrepareResponse)
async def prepare_document_upload(
    file: UploadFile,
    cache: DocumentCache,
    settings: SettingsDep,
) -> DocumentPrepareResponse:
    """Prepare a document from file upload."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Empty file")

    cache_key = hashlib.sha256(content).hexdigest()
    cached_data = await cache.retrieve_data(cache_key)
    if cached_data:
        cached_doc = CachedDocument.model_validate_json(cached_data)
        uncached_pages = (
            get_uncached_pages(cached_doc, None) if _needs_ocr_processing(cached_doc.metadata.content_type) else set()
        )
        return DocumentPrepareResponse(
            hash=cache_key,
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
    await cache.store(
        cache_key, cached_doc.model_dump_json().encode(), ttl_seconds=settings.document_cache_ttl_document
    )

    uncached_pages = get_uncached_pages(cached_doc, None) if _needs_ocr_processing(content_type) else set()
    return DocumentPrepareResponse(
        hash=cache_key, metadata=metadata, endpoint="document", uncached_pages=uncached_pages
    )


@router.post("/text", response_model=DocumentCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_text_document(
    req: TextDocumentCreateRequest,
    db: DbSession,
    settings: SettingsDep,
    user: AuthenticatedUser,
) -> DocumentCreateResponse:
    """Create a document from direct text input."""
    ast = parse_markdown(req.content)
    structured_doc = transform_to_document(ast, max_block_chars=settings.max_block_chars)
    structured_content = structured_doc.model_dump_json()
    text_blocks = structured_doc.get_audio_blocks()

    doc = await _create_document_with_blocks(
        db=db,
        user_id=user.id,
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
) -> DocumentCreateResponse:
    """Create a document from a live website."""
    cached_data = await cache.retrieve_data(req.hash)
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
    if cached_doc.metadata.url:
        markdown = _resolve_relative_urls(markdown, cached_doc.metadata.url)
    extraction_result = DocumentExtractionResult(
        pages={0: ExtractedPage(markdown=markdown, images=[])},
        extraction_method="markitdown",
    )

    cached_doc.extraction = extraction_result
    await cache.store(
        req.hash,
        cached_doc.model_dump_json().encode(),
        ttl_seconds=settings.document_cache_ttl_webpage,
    )

    extracted_text = extraction_result.pages[0].markdown  # website are just a single page

    ast = parse_markdown(extracted_text)
    structured_doc = transform_to_document(ast, max_block_chars=settings.max_block_chars)
    structured_content = structured_doc.model_dump_json()
    text_blocks = structured_doc.get_audio_blocks()

    doc = await _create_document_with_blocks(
        db=db,
        user_id=user.id,
        title=cached_doc.metadata.title or req.title,
        original_text=extracted_text,
        filtered_text=None,  # TODO: Implement filtering
        structured_content=structured_content,
        metadata=cached_doc.metadata,
        extraction_method=extraction_result.extraction_method,
        text_blocks=text_blocks,
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
    cache: DocumentCache,
    settings: SettingsDep,
    user: AuthenticatedUser,
    is_admin: IsAdmin,
    document_processor_manager: DocumentProcessorManagerDep,
) -> DocumentCreateResponse:
    """Create a document from a file (PDF, image, etc)."""
    cached_data = await cache.retrieve_data(req.hash)
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

    processor = document_processor_manager.get_processor(req.processor_slug)
    if not processor:
        raise ResourceNotFoundError(DocumentProcessor.__name__, req.processor_slug)

    extraction_result = await processor.process_with_billing(
        user_id=user.id,
        cache_key=req.hash,
        db=db,
        cache=cache,
        url=cached_doc.metadata.url,
        content=cached_doc.content,
        content_type=cached_doc.metadata.content_type,
        pages=req.pages,
        is_admin=is_admin,
    )

    extracted_text: str = "\n\n".join(page.markdown for page in extraction_result.pages.values())

    ast = parse_markdown(extracted_text)
    structured_doc = transform_to_document(ast, max_block_chars=settings.max_block_chars)
    structured_content = structured_doc.model_dump_json()
    text_blocks = structured_doc.get_audio_blocks()

    doc = await _create_document_with_blocks(
        db=db,
        user_id=user.id,
        title=cached_doc.metadata.title or req.title,
        original_text=extracted_text,
        filtered_text=None,  # TODO: Implement filtering
        structured_content=structured_content,
        metadata=cached_doc.metadata,
        extraction_method=extraction_result.extraction_method,
        text_blocks=text_blocks,
    )
    return DocumentCreateResponse(id=doc.id, title=doc.title)


class DocumentListItem(BaseModel):
    """Minimal document info for list view."""

    id: UUID
    title: str | None
    created: str  # ISO format


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
    return [DocumentListItem(id=doc.id, title=doc.title, created=doc.created.isoformat()) for doc in result.all()]


@router.get("/{document_id}")
async def get_document(document: CurrentDoc) -> Document:
    return document


class DocumentUpdateRequest(BaseModel):
    title: str | None = None


@router.patch("/{document_id}", response_model=DocumentCreateResponse)
async def update_document(
    document: CurrentDoc,
    request: DocumentUpdateRequest,
    db: DbSession,
) -> DocumentCreateResponse:
    """Update document properties (currently just title)."""
    if request.title is not None:
        document.title = request.title
    await db.commit()
    await db.refresh(document)
    return DocumentCreateResponse(id=document.id, title=document.title)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document: CurrentDoc,
    db: DbSession,
) -> None:
    """Delete a document and all its blocks."""
    await db.delete(document)
    await db.commit()


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
    # User-Agent required by Wikipedia and many other sites (they block requests without it)
    headers = {"User-Agent": "Yapit/1.0 (https://yapit.app; document fetcher)"}
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0, headers=headers) as client:
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
            content_type = response.headers.get("content-type", "application/octet-stream")
            return content.getvalue(), content_type
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"URL returned error: HTTP {e.response.status_code}",
            )
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


async def _create_document_with_blocks(
    db: DbSession,
    user_id: str,
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
        title=title,
        original_text=original_text,
        filtered_text=filtered_text,
        extraction_method=extraction_method,
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
