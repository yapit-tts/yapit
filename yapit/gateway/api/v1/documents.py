import asyncio
import datetime as dt
import hashlib
import json
import re
import time
from datetime import datetime
from email.message import EmailMessage
from html import escape as html_escape
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

import pymupdf
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import HTMLResponse
from loguru import logger
from pydantic import BaseModel, Field, HttpUrl, StringConstraints
from sqlmodel import col, func, select

from yapit.contracts import (
    MAX_CONCURRENT_EXTRACTIONS,
    MAX_STORAGE_FREE,
    MAX_STORAGE_GUEST,
    MAX_STORAGE_PAID,
    RATELIMIT_EXTRACTION,
)
from yapit.gateway.auth import authenticate
from yapit.gateway.cache import Cache
from yapit.gateway.constants import SUPPORTED_WEB_MIME_TYPES
from yapit.gateway.db import create_session
from yapit.gateway.deps import (
    AiExtractorConfigDep,
    AiExtractorDep,
    AuthenticatedUser,
    CurrentDoc,
    DbSession,
    DocumentCache,
    ExtractionCache,
    ImageStorageDep,
    RedisClient,
    SettingsDep,
)
from yapit.gateway.document.batch import BatchJobInfo, BatchJobStatus, get_batch_job, save_batch_job, submit_batch_job
from yapit.gateway.document.extraction import PER_PAGE_TOLERANCE, estimate_document_tokens
from yapit.gateway.document.http import download_document
from yapit.gateway.document.markxiv import detect_arxiv_url, fetch_from_markxiv
from yapit.gateway.document.processing import (
    CachedDocument,
    DocumentExtractionResult,
    ExtractedPage,
    ProcessorConfig,
    cpu_executor,
    create_document_with_blocks,
    process_pages_to_document,
    process_with_billing,
)
from yapit.gateway.document.processors import pdf
from yapit.gateway.document.website import extract_website_content
from yapit.gateway.domain_models import Block, Document, DocumentMetadata, UsageType, UserPreferences, UserSubscription
from yapit.gateway.exceptions import ResourceNotFoundError
from yapit.gateway.metrics import log_event
from yapit.gateway.reservations import create_reservation, release_reservation
from yapit.gateway.usage import check_usage_limit

router = APIRouter(prefix="/v1/documents", tags=["Documents"], dependencies=[Depends(authenticate)])
public_router = APIRouter(prefix="/v1/documents", tags=["Documents"])


@public_router.get("/supported-formats")
async def get_supported_formats(ai_config: AiExtractorConfigDep) -> dict:
    formats = {
        "application/pdf": {"free": True, "ai": True, "has_pages": True, "batch": True},
        "text/html": {"free": True, "ai": False, "has_pages": False, "batch": False},
        "text/plain": {"free": True, "ai": False, "has_pages": False, "batch": False},
        "text/markdown": {"free": True, "ai": False, "has_pages": False, "batch": False},
        "text/x-markdown": {"free": True, "ai": False, "has_pages": False, "batch": False},
    }
    # Types only reachable via AI — no free processor exists for these
    if ai_config:
        for mime_type in ai_config.supported_mime_types:
            if mime_type not in formats:
                formats[mime_type] = {"free": False, "ai": True, "has_pages": False, "batch": True}

    return {"formats": formats, "accept": ",".join(sorted(formats))}


def _format_size(bytes_: int) -> str:
    """Format bytes as human-readable string."""
    if bytes_ >= 1024 * 1024:
        return f"{bytes_ / (1024 * 1024):.1f}MB"
    if bytes_ >= 1024:
        return f"{bytes_ / 1024:.1f}KB"
    return f"{bytes_}B"


async def check_storage_limit(user_id: str, is_anonymous: bool, db: DbSession) -> None:
    """Check if user has storage capacity. Raises HTTPException if at limit."""
    if is_anonymous:
        limit = MAX_STORAGE_GUEST
    else:
        result = await db.exec(select(UserSubscription).where(UserSubscription.user_id == user_id))
        subscription = result.first()
        limit = MAX_STORAGE_PAID if subscription and subscription.ever_paid else MAX_STORAGE_FREE

    # Sum of original_text + structured_content for all user's documents
    usage_result = await db.exec(
        select(
            func.coalesce(func.sum(func.length(Document.original_text)), 0)
            + func.coalesce(func.sum(func.length(Document.structured_content)), 0)
        ).where(Document.user_id == user_id)
    )
    usage = usage_result.one()

    if usage >= limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "STORAGE_LIMIT_EXCEEDED",
                "message": f"Storage limit reached ({_format_size(usage)} / {_format_size(limit)}).",
            },
        )


class DocumentPrepareRequest(BaseModel):
    url: HttpUrl


class DocumentPrepareResponse(BaseModel):
    """Response with document metadata for preparation.

    Args:
        hash: SHA256 hash of the document content (for uploads) or url (for urls), used as cache key
        content_hash: SHA256 hash of actual content (for extraction progress tracking)
        endpoint: Which API endpoint the client should use to create the document
        uncached_pages: Page numbers without AI extraction cache (empty if AI extractor not configured/supported)
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

    content: Annotated[str, StringConstraints(min_length=1, max_length=500_000, strip_whitespace=True)]


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
        ai_transform: Use AI-powered extraction (requires subscription). False = free extraction.
        batch_mode: Submit as batch job (50% cheaper, async). Only valid with ai_transform=True.
    """

    pages: list[int] | None = None
    ai_transform: bool = False
    batch_mode: bool = False


class WebsiteDocumentCreateRequest(BasePreparedDocumentCreateRequest):
    """Create document from a live website."""


class DocumentCreateResponse(BaseModel):
    """Response after document creation."""

    id: UUID
    title: str | None
    failed_pages: list[int] = []  # Pages that failed extraction (0-indexed)


class ExtractionAcceptedResponse(BaseModel):
    """Response when extraction is accepted for background processing."""

    extraction_id: str
    content_hash: str
    total_pages: int


class BatchSubmittedResponse(BaseModel):
    """Response after batch job submission."""

    content_hash: str
    total_pages: int
    submitted_at: str


class ExtractionStatusResponse(BaseModel):
    """Progress of an ongoing extraction."""

    total_pages: int
    completed_pages: list[int]
    status: Literal["processing", "complete", "not_found"]
    document_id: UUID | None = None
    error: str | None = None
    failed_pages: list[int] = []


class BatchStatusResponse(BaseModel):
    """Status of a batch extraction job."""

    status: str  # PENDING, RUNNING, SUCCEEDED, FAILED, EXPIRED
    submitted_at: str
    total_pages: int
    document_id: UUID | None = None
    error: str | None = None


class ExtractionStatusRequest(BaseModel):
    extraction_id: str | None = None
    content_hash: str
    ai_transform: bool
    pages: list[int]


@router.post("/extraction/status", response_model=ExtractionStatusResponse)
async def get_extraction_status(
    req: ExtractionStatusRequest,
    extraction_cache: ExtractionCache,
    ai_extractor_config: AiExtractorConfigDep,
    redis: RedisClient,
) -> ExtractionStatusResponse:
    """Get progress of an ongoing document extraction.

    Checks two sources:
    1. Per-page extraction cache (progress tracking)
    2. Redis async extraction result (document_id or error when done)
    """
    raw_result = None
    if req.extraction_id:
        raw_result = await redis.get(_async_extraction_key(req.extraction_id))
    if raw_result:
        result = json.loads(raw_result)
        if "error" in result:
            return ExtractionStatusResponse(
                total_pages=len(req.pages),
                completed_pages=[],
                status="complete",
                error=result["error"],
            )
        return ExtractionStatusResponse(
            total_pages=len(req.pages),
            completed_pages=list(range(len(req.pages))),
            status="complete",
            document_id=result["document_id"],
            failed_pages=result.get("failed_pages", []),
        )

    # Check per-page extraction cache for progress (only AI extraction is cached)
    config = ai_extractor_config if (req.ai_transform and ai_extractor_config) else None
    if not config or not config.extraction_cache_prefix:
        return ExtractionStatusResponse(total_pages=len(req.pages), completed_pages=[], status="processing")

    keys = [config.extraction_cache_key(req.content_hash, idx) for idx in req.pages]
    cached_keys = await extraction_cache.batch_exists(keys)
    completed = [idx for idx, key in zip(req.pages, keys) if key in cached_keys]

    return ExtractionStatusResponse(
        total_pages=len(req.pages),
        completed_pages=completed,
        status="processing",
    )


class CancelExtractionRequest(BaseModel):
    extraction_id: str


class CancelExtractionResponse(BaseModel):
    status: Literal["cancelled", "not_found"]


@router.post("/extraction/cancel", response_model=CancelExtractionResponse)
async def cancel_extraction(
    req: CancelExtractionRequest,
    redis: RedisClient,
) -> CancelExtractionResponse:
    """Cancel an ongoing document extraction.

    Sets a Redis flag that gemini.py checks before processing each page.
    Pages already in-flight will complete, but pending pages will be skipped.
    """
    cancel_key = f"extraction:cancel:{req.extraction_id}"
    await redis.set(cancel_key, "1", ex=300)
    logger.info(f"Extraction cancel requested for {req.extraction_id}")
    return CancelExtractionResponse(status="cancelled")


@router.get("/batch/{content_hash}/status", response_model=BatchStatusResponse)
async def get_batch_status(
    content_hash: str,
    redis: RedisClient,
    user: AuthenticatedUser,
) -> BatchStatusResponse:
    """Get status of a batch extraction job."""
    job = await get_batch_job(redis, content_hash)
    if not job:
        raise ResourceNotFoundError("BatchJob", content_hash)
    if job.user_id != user.id:
        raise ResourceNotFoundError("BatchJob", content_hash)

    return BatchStatusResponse(
        status=job.status.value,
        submitted_at=job.submitted_at,
        total_pages=job.total_pages,
        document_id=UUID(job.document_id) if job.document_id else None,
        error=job.error,
    )


@router.post("/prepare", response_model=DocumentPrepareResponse)
async def prepare_document(
    request: DocumentPrepareRequest,
    file_cache: DocumentCache,
    extraction_cache: ExtractionCache,
    settings: SettingsDep,
    ai_extractor_config: AiExtractorConfigDep,
) -> DocumentPrepareResponse:
    """Prepare a document from URL for creation."""
    url_hash = hashlib.sha256(str(request.url).encode()).hexdigest()

    # Check URL cache first (same URL within TTL = no download needed)
    cached_data = await file_cache.retrieve_data(url_hash)
    if cached_data:
        cached_doc = CachedDocument.model_validate_json(cached_data)
        await log_event(
            "document_cache_hit",
            data={"cache_type": "url", "content_type": cached_doc.metadata.content_type},
        )
        endpoint = _get_endpoint_type_from_content_type(cached_doc.metadata.content_type)
        # Compute content_hash for extraction cache lookup
        content_hash = hashlib.sha256(cached_doc.content).hexdigest() if cached_doc.content else url_hash
        has_ai = ai_extractor_config and ai_extractor_config.is_supported(cached_doc.metadata.content_type)
        if has_ai:
            assert ai_extractor_config is not None
            uncached_pages = await _get_uncached_pages(
                content_hash, cached_doc.metadata.total_pages, extraction_cache, ai_extractor_config
            )
        else:
            uncached_pages: set[int] = set()
        return DocumentPrepareResponse(
            hash=url_hash,
            content_hash=content_hash,
            metadata=cached_doc.metadata,
            endpoint=endpoint,
            uncached_pages=uncached_pages,
        )

    content, content_type = await download_document(request.url, settings.document_max_download_size)

    page_count, title = await asyncio.to_thread(_extract_document_info, content, content_type)
    metadata = DocumentMetadata(
        content_type=content_type,
        total_pages=page_count,
        title=title,
        url=str(request.url),
        file_name=Path(request.url.path or "/").name or None,
        file_size=len(content),
    )

    endpoint = _get_endpoint_type_from_content_type(content_type)
    cached_doc = CachedDocument(content=content, metadata=metadata)
    await file_cache.store(url_hash, cached_doc.model_dump_json().encode())

    content_hash = hashlib.sha256(content).hexdigest()
    has_ai = ai_extractor_config and ai_extractor_config.is_supported(content_type)
    if has_ai:
        assert ai_extractor_config is not None
        uncached_pages = await _get_uncached_pages(
            content_hash, metadata.total_pages, extraction_cache, ai_extractor_config
        )
    else:
        uncached_pages: set[int] = set()
    return DocumentPrepareResponse(
        hash=url_hash, content_hash=content_hash, metadata=metadata, endpoint=endpoint, uncached_pages=uncached_pages
    )


@router.post("/prepare/upload", response_model=DocumentPrepareResponse)
async def prepare_document_upload(
    file: UploadFile,
    file_cache: DocumentCache,
    extraction_cache: ExtractionCache,
    ai_extractor_config: AiExtractorConfigDep,
) -> DocumentPrepareResponse:
    """Prepare a document from file upload."""
    t0 = time.monotonic()
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Empty file")

    cache_key = hashlib.sha256(content).hexdigest()
    t_hash = time.monotonic()
    cached_data = await file_cache.retrieve_data(cache_key)
    t_cache_check = time.monotonic()
    if cached_data:
        cached_doc = CachedDocument.model_validate_json(cached_data)
        await log_event(
            "document_cache_hit",
            data={"cache_type": "upload", "content_type": cached_doc.metadata.content_type},
        )
        has_ai = ai_extractor_config and ai_extractor_config.is_supported(cached_doc.metadata.content_type)
        if has_ai:
            assert ai_extractor_config is not None
            uncached_pages = await _get_uncached_pages(
                cache_key, cached_doc.metadata.total_pages, extraction_cache, ai_extractor_config
            )
        else:
            uncached_pages: set[int] = set()
        logger.info(
            f"prepare/upload cache hit: read={t_hash - t0:.2f}s, "
            f"cache_check={t_cache_check - t_hash:.2f}s, total={time.monotonic() - t0:.2f}s"
        )
        return DocumentPrepareResponse(
            hash=cache_key,
            content_hash=cache_key,
            metadata=cached_doc.metadata,
            endpoint=_get_endpoint_type_from_content_type(cached_doc.metadata.content_type),
            uncached_pages=uncached_pages,
        )

    content_type = file.content_type or "application/octet-stream"

    total_pages, title = await asyncio.to_thread(_extract_document_info, content, content_type)
    t_info = time.monotonic()
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
    t_store = time.monotonic()

    has_ai = ai_extractor_config and ai_extractor_config.is_supported(content_type)
    if has_ai:
        assert ai_extractor_config is not None
        uncached_pages = await _get_uncached_pages(
            cache_key, metadata.total_pages, extraction_cache, ai_extractor_config
        )
    else:
        uncached_pages: set[int] = set()
    logger.info(
        f"prepare/upload: read={t_hash - t0:.2f}s, cache_check={t_cache_check - t_hash:.2f}s, "
        f"extract_info={t_info - t_cache_check:.2f}s, store={t_store - t_info:.2f}s, "
        f"uncached_pages={time.monotonic() - t_store:.2f}s, total={time.monotonic() - t0:.2f}s"
    )
    endpoint = _get_endpoint_type_from_content_type(content_type)
    return DocumentPrepareResponse(
        hash=cache_key, content_hash=cache_key, metadata=metadata, endpoint=endpoint, uncached_pages=uncached_pages
    )


@router.post("/text", response_model=DocumentCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_text_document(
    req: TextDocumentCreateRequest,
    db: DbSession,
    settings: SettingsDep,
    user: AuthenticatedUser,
) -> DocumentCreateResponse:
    """Create a document from direct text input."""
    await check_storage_limit(user.id, user.is_anonymous, db)
    prefs = await db.get(UserPreferences, user.id)

    processed = await asyncio.get_running_loop().run_in_executor(
        cpu_executor,
        process_pages_to_document,
        {0: ExtractedPage(markdown=req.content, images=[])},
        settings,
    )

    doc = await create_document_with_blocks(
        db=db,
        user_id=user.id,
        title=req.title,
        original_text=processed.extracted_text,
        structured_content=processed.structured_content,
        metadata=DocumentMetadata(
            content_type="text/plain",
            total_pages=1,
            title=None,
            url=None,
            file_name=None,
            file_size=len(req.content.encode("utf-8")),
        ),
        extraction_method=None,
        text_blocks=processed.text_blocks,
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
    await check_storage_limit(user.id, user.is_anonymous, db)
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

    markdown, extraction_method = await extract_website_content(
        cached_doc.content, cached_doc.metadata.url, settings.markxiv_url
    )

    processed = await asyncio.get_running_loop().run_in_executor(
        cpu_executor,
        process_pages_to_document,
        {0: ExtractedPage(markdown=markdown, images=[])},
        settings,
    )

    doc = await create_document_with_blocks(
        db=db,
        user_id=user.id,
        title=cached_doc.metadata.title or req.title or cached_doc.metadata.file_name,
        original_text=processed.extracted_text,
        structured_content=processed.structured_content,
        metadata=cached_doc.metadata,
        extraction_method=extraction_method,
        text_blocks=processed.text_blocks,
        is_public=prefs.default_documents_public if prefs else False,
    )
    return DocumentCreateResponse(id=doc.id, title=doc.title)


async def _billing_precheck(
    config: ProcessorConfig,
    content: bytes,
    content_type: str,
    content_hash: str,
    user_id: str,
    pages: list[int] | None,
    db: DbSession,
    billing_enabled: bool,
    redis: RedisClient,
) -> None:
    """Estimate tokens, check usage limit, create reservation."""
    estimate = estimate_document_tokens(content, content_type, config.output_token_multiplier, pages)
    tolerance = PER_PAGE_TOLERANCE * estimate.num_pages
    amount_to_check = max(0, estimate.total_tokens - tolerance)

    await check_usage_limit(
        user_id,
        UsageType.ocr_tokens,
        amount_to_check,
        db,
        billing_enabled=billing_enabled,
        redis=redis,
    )
    await create_reservation(redis, user_id, content_hash, estimate.total_tokens)


async def _submit_batch_extraction(
    content: bytes,
    content_type: str,
    content_hash: str,
    total_pages: int,
    file_size: int,
    title: str | None,
    pages: list[int] | None,
    user_id: str,
    db: DbSession,
    settings: SettingsDep,
    ai_extractor_config: AiExtractorConfigDep,
    ai_extractor: AiExtractorDep,
    redis: RedisClient,
) -> BatchSubmittedResponse:
    """Submit document for batch extraction via Gemini Batch API.

    Returns immediately after billing checks. YOLO detection and batch
    submission happen in a background task — the job starts as PREPARING
    and transitions to PENDING once submitted to Gemini.
    """
    if not ai_extractor or not ai_extractor_config:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI transform not configured on this server",
        )

    await _billing_precheck(
        config=ai_extractor_config,
        content=content,
        content_type=content_type,
        content_hash=content_hash,
        user_id=user_id,
        pages=pages,
        db=db,
        billing_enabled=settings.billing_enabled,
        redis=redis,
    )

    pages_requested = list(range(total_pages)) if pages is None else pages
    submitted_at = datetime.now(tz=dt.UTC).isoformat()

    job_info = BatchJobInfo(
        user_id=user_id,
        content_hash=content_hash,
        total_pages=len(pages_requested),
        submitted_at=submitted_at,
        status=BatchJobStatus.PREPARING,
        title=title,
        content_type=content_type,
        file_size=file_size,
        pages_requested=pages_requested,
        figure_urls_by_page={},
    )
    await save_batch_job(redis, job_info)

    asyncio.create_task(
        _prepare_and_submit_batch(
            content=content,
            content_hash=content_hash,
            pages=pages,
            user_id=user_id,
            ai_extractor=ai_extractor,
            redis=redis,
            title=title,
            content_type=content_type,
            file_size=file_size,
            pages_requested=pages_requested,
        )
    )

    return BatchSubmittedResponse(
        content_hash=content_hash,
        total_pages=len(pages_requested),
        submitted_at=submitted_at,
    )


async def _prepare_and_submit_batch(
    content: bytes,
    content_hash: str,
    pages: list[int] | None,
    user_id: str,
    ai_extractor: AiExtractorDep,
    redis: RedisClient,
    title: str | None,
    content_type: str,
    file_size: int,
    pages_requested: list[int],
) -> None:
    """Background task: run YOLO detection + submit batch to Gemini."""
    assert ai_extractor is not None
    try:
        batch_requests, figure_urls_by_page = await ai_extractor.prepare_for_batch(
            content,
            content_hash,
            pages,
        )

        await submit_batch_job(
            client=ai_extractor.client,
            redis=redis,
            user_id=user_id,
            content_hash=content_hash,
            model=ai_extractor.model,
            page_requests=batch_requests,
            title=title,
            content_type=content_type,
            file_size=file_size,
            pages_requested=pages_requested,
            figure_urls_by_page=figure_urls_by_page,
        )
    except Exception:
        logger.exception(f"Batch preparation failed for {content_hash}")
        await release_reservation(redis, user_id, content_hash)
        job = await get_batch_job(redis, content_hash)
        if job:
            job.status = BatchJobStatus.FAILED
            job.error = "Batch preparation failed. Please try again."
            await save_batch_job(redis, job)


ASYNC_EXTRACTION_RESULT_TTL = 3600


def _async_extraction_key(extraction_id: str) -> str:
    return f"async_extraction:{extraction_id}"


async def _run_extraction(
    extraction_id: str,
    content: bytes,
    content_type: str,
    content_hash: str,
    total_pages: int,
    file_size: int,
    ai_transform: bool,
    arxiv_id: str | None,
    title: str | None,
    pages: list[int] | None,
    user_id: str,
    is_public: bool,
    metadata: DocumentMetadata,
    settings: SettingsDep,
    extraction_cache: ExtractionCache,
    image_storage: ImageStorageDep,
    ai_extractor_config: AiExtractorConfigDep,
    ai_extractor: AiExtractorDep,
    redis: RedisClient,
    ratelimit_key: str,
) -> None:
    """Background task: extract document, create in DB, store result in Redis."""
    result_key = _async_extraction_key(extraction_id)

    cancel_key = f"extraction:cancel:{extraction_id}"

    method = "ai" if ai_transform else "free"
    if arxiv_id:
        method = "markxiv"
    logger.info(f"Extraction {extraction_id} starting: {method}, {total_pages} pages, hash={content_hash[:12]}")

    try:
        async for db in create_session(settings):
            if arxiv_id and settings.markxiv_url:
                markdown = await fetch_from_markxiv(settings.markxiv_url, arxiv_id)
                extraction_result = DocumentExtractionResult(
                    pages={0: ExtractedPage(markdown=markdown, images=[])},
                    extraction_method="markxiv",
                )
            elif content_type.startswith("text/") and not ai_transform:
                # Text content doesn't need extraction — pass through as-is
                extraction_result = DocumentExtractionResult(
                    pages={0: ExtractedPage(markdown=content.decode("utf-8", errors="ignore"), images=[])},
                    extraction_method="passthrough",
                )
            else:
                if ai_transform:
                    assert ai_extractor is not None and ai_extractor_config is not None
                    config = ai_extractor_config
                    extractor = ai_extractor.extract(
                        content,
                        content_type,
                        content_hash,
                        pages,
                        user_id=user_id,
                        cancel_key=cancel_key,
                    )
                else:
                    config = pdf.config
                    extractor = pdf.extract(content, pages)

                logger.info(f"Extraction {extraction_id}: starting process_with_billing")
                extraction_result = await process_with_billing(
                    config=config,
                    extractor=extractor,
                    user_id=user_id,
                    content=content,
                    content_type=content_type,
                    content_hash=content_hash,
                    total_pages=total_pages,
                    db=db,
                    extraction_cache=extraction_cache,
                    image_storage=image_storage,
                    redis=redis,
                    billing_enabled=settings.billing_enabled,
                    file_size=file_size,
                    pages=pages,
                )
                logger.info(
                    f"Extraction {extraction_id}: extraction done, "
                    f"{len(extraction_result.pages)} pages, {len(extraction_result.failed_pages)} failed"
                )

            if await redis.exists(cancel_key):
                logger.info(f"Extraction {extraction_id} cancelled, skipping document creation")
                return

            if not extraction_result.pages:
                await redis.set(
                    result_key,
                    json.dumps({"error": "Document extraction failed. Please try again later."}),
                    ex=ASYNC_EXTRACTION_RESULT_TTL,
                )
                return

            logger.info(f"Extraction {extraction_id}: building structured document")
            processed = await asyncio.get_running_loop().run_in_executor(
                cpu_executor, process_pages_to_document, extraction_result.pages, settings
            )
            logger.info(f"Extraction {extraction_id}: creating document in DB")
            doc = await create_document_with_blocks(
                db=db,
                user_id=user_id,
                title=title,
                original_text=processed.extracted_text,
                structured_content=processed.structured_content,
                metadata=metadata,
                extraction_method=extraction_result.extraction_method,
                text_blocks=processed.text_blocks,
                is_public=is_public,
                content_hash=content_hash,
            )

            await redis.set(
                result_key,
                json.dumps(
                    {
                        "document_id": str(doc.id),
                        "title": doc.title,
                        "failed_pages": extraction_result.failed_pages,
                    }
                ),
                ex=ASYNC_EXTRACTION_RESULT_TTL,
            )
            break  # create_session is an async generator; only need one session
    except Exception:
        logger.exception(f"Async extraction failed for {content_hash}")
        try:
            await redis.set(
                result_key,
                json.dumps({"error": "Extraction failed. Please try again."}),
                ex=ASYNC_EXTRACTION_RESULT_TTL,
            )
        except Exception:
            logger.exception(f"Failed to store extraction error for {content_hash}")
    finally:
        await redis.decr(ratelimit_key)
        # Safety net: release precheck reservation regardless of outcome.
        # Harmless no-op if process_with_billing() already released it.
        if ai_transform:
            await release_reservation(redis, user_id, content_hash)


@router.post(
    "/document",
    response_model=ExtractionAcceptedResponse | BatchSubmittedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_document(
    req: DocumentCreateRequest,
    db: DbSession,
    file_cache: DocumentCache,
    extraction_cache: ExtractionCache,
    image_storage: ImageStorageDep,
    settings: SettingsDep,
    user: AuthenticatedUser,
    ai_extractor_config: AiExtractorConfigDep,
    ai_extractor: AiExtractorDep,
    redis: RedisClient,
) -> ExtractionAcceptedResponse | BatchSubmittedResponse:
    """Create a document from a file (PDF, image, etc).

    Returns 202 immediately. Extraction runs in background.
    Poll /extraction/status for document_id when complete.
    """
    await check_storage_limit(user.id, user.is_anonymous, db)
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
    if not cached_doc.content:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Cached document has no content",
        )

    content_hash = hashlib.sha256(cached_doc.content).hexdigest()

    if req.batch_mode and not req.ai_transform:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="batch_mode requires ai_transform=true",
        )

    if req.batch_mode:
        return await _submit_batch_extraction(
            content=cached_doc.content,
            content_type=cached_doc.metadata.content_type,
            content_hash=content_hash,
            total_pages=cached_doc.metadata.total_pages,
            file_size=cached_doc.metadata.file_size or len(cached_doc.content),
            title=cached_doc.metadata.title or req.title or cached_doc.metadata.file_name,
            pages=req.pages,
            user_id=user.id,
            db=db,
            settings=settings,
            ai_extractor_config=ai_extractor_config,
            ai_extractor=ai_extractor,
            redis=redis,
        )

    # AI extraction requires extractor to be configured
    if req.ai_transform:
        if not ai_extractor or not ai_extractor_config:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI transform not configured on this server",
            )

    # Rate limit (sync — returns 429 immediately)
    ratelimit_key = RATELIMIT_EXTRACTION.format(user_id=user.id)
    current = await redis.incr(ratelimit_key)
    await redis.expire(ratelimit_key, 600)
    if current > MAX_CONCURRENT_EXTRACTIONS:
        await redis.decr(ratelimit_key)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many concurrent document extractions. Please wait for current extractions to complete.",
        )

    # Billing pre-check (sync — returns 402 immediately)
    if req.ai_transform:
        assert ai_extractor_config is not None  # checked above
        await _billing_precheck(
            config=ai_extractor_config,
            content=cached_doc.content,
            content_type=cached_doc.metadata.content_type,
            content_hash=content_hash,
            user_id=user.id,
            pages=req.pages,
            db=db,
            billing_enabled=settings.billing_enabled,
            redis=redis,
        )

    arxiv_match = detect_arxiv_url(cached_doc.metadata.url) if cached_doc.metadata.url else None
    arxiv_id = arxiv_match[0] if arxiv_match and settings.markxiv_url and not req.ai_transform else None

    extraction_id = str(uuid4())

    asyncio.create_task(
        _run_extraction(
            extraction_id=extraction_id,
            content=cached_doc.content,
            content_type=cached_doc.metadata.content_type,
            content_hash=content_hash,
            total_pages=cached_doc.metadata.total_pages,
            file_size=cached_doc.metadata.file_size or len(cached_doc.content),
            ai_transform=req.ai_transform,
            arxiv_id=arxiv_id,
            title=cached_doc.metadata.title or req.title or cached_doc.metadata.file_name,
            pages=req.pages,
            user_id=user.id,
            is_public=prefs.default_documents_public if prefs else False,
            metadata=cached_doc.metadata,
            settings=settings,
            extraction_cache=extraction_cache,
            image_storage=image_storage,
            ai_extractor_config=ai_extractor_config,
            ai_extractor=ai_extractor,
            redis=redis,
            ratelimit_key=ratelimit_key,
        )
    )

    return ExtractionAcceptedResponse(
        extraction_id=extraction_id,
        content_hash=content_hash,
        total_pages=cached_doc.metadata.total_pages,
    )


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


class BulkDeleteResponse(BaseModel):
    deleted_count: int


@router.delete("/bulk", response_model=BulkDeleteResponse)
async def bulk_delete_documents(
    db: DbSession,
    image_storage: ImageStorageDep,
    user: AuthenticatedUser,
    older_than_days: int | None = Query(None, ge=1, description="Only delete documents older than X days"),
) -> BulkDeleteResponse:
    """Delete multiple documents. If older_than_days is provided, only delete documents older than that."""
    query = select(Document).where(Document.user_id == user.id)

    if older_than_days:
        cutoff = datetime.now(dt.UTC) - dt.timedelta(days=older_than_days)
        query = query.where(Document.created < cutoff)

    result = await db.exec(query)
    documents = result.all()

    # Collect content hashes for image cleanup
    content_hashes = {doc.content_hash for doc in documents if doc.content_hash}

    for doc in documents:
        await db.delete(doc)

    await db.commit()

    # Clean up images for content hashes no longer referenced
    still_referenced: set[str] = set()
    if content_hashes:
        result = await db.exec(
            select(Document.content_hash).where(col(Document.content_hash).in_(content_hashes)).distinct()
        )
        still_referenced = set(result.all())
    for content_hash in content_hashes - still_referenced:
        await image_storage.delete_all(content_hash)

    return BulkDeleteResponse(deleted_count=len(documents))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document: CurrentDoc,
    db: DbSession,
    image_storage: ImageStorageDep,
) -> None:
    """Delete a document and all its blocks. Cleans up images if last doc with this content."""
    content_hash = document.content_hash

    await db.delete(document)
    await db.commit()

    # Clean up images if no other documents use this content
    if content_hash:
        other_docs = await db.exec(select(Document).where(Document.content_hash == content_hash).limit(1))
        if not other_docs.first():
            await image_storage.delete_all(content_hash)


@router.get("/{document_id}/blocks")
async def get_document_blocks(
    document: CurrentDoc,
    db: DbSession,
) -> list[Block]:
    """Get all document blocks for playback.

    Returns all blocks without pagination - needed for playback to work correctly.
    Data size is small (~200 bytes/block), so even 1000+ blocks is fine.
    """
    result = await db.exec(select(Block).where(Block.document_id == document.id).order_by(col(Block.idx)))
    return list(result.all())


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
    result = await db.exec(select(Document).where(Document.id == document_id, col(Document.is_public).is_(True)))
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
    result = await db.exec(select(Document).where(Document.id == document_id, col(Document.is_public).is_(True)))
    document = result.first()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    result = await db.exec(select(Block).where(Block.document_id == document_id).order_by(col(Block.idx)))
    return list(result.all())


@public_router.get("/{document_id}/og-preview", response_class=HTMLResponse)
async def get_og_preview(document_id: UUID, db: DbSession) -> HTMLResponse:
    """Return HTML with og:* meta tags for social media bots."""
    result = await db.exec(select(Document).where(Document.id == document_id, col(Document.is_public).is_(True)))
    document = result.first()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    title = html_escape(document.title or "Untitled")
    url = f"https://yapit.md/listen/{document_id}"

    # No meta refresh - bots don't follow redirects, and caching could cause redirect loops
    # if Safari/iOS serves a cached bot response to regular users
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta property="og:type" content="website" />
    <meta property="og:title" content="{title}" />
    <meta property="og:description" content="Listen on Yapit" />
    <meta property="og:image" content="https://yapit.md/og-image.png" />
    <meta property="og:url" content="{url}" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{title}" />
    <meta name="twitter:description" content="Listen on Yapit" />
    <meta name="twitter:image" content="https://yapit.md/og-image.png" />
    <title>{title}</title>
</head>
<body>
    <p>Visit <a href="{url}">{title}</a> on Yapit</p>
</body>
</html>"""
    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "no-store, max-age=0"},
    )


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
    await check_storage_limit(user.id, user.is_anonymous, db)
    result = await db.exec(select(Document).where(Document.id == document_id, col(Document.is_public).is_(True)))
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
    source_blocks = await db.exec(select(Block).where(Block.document_id == document_id).order_by(col(Block.idx)))
    db.add_all(
        [
            Block(
                document_id=new_doc.id,
                document=new_doc,
                idx=block.idx,
                text=block.text,
            )
            for block in source_blocks.all()
        ]
    )

    await db.commit()
    return DocumentImportResponse(id=new_doc.id, title=new_doc.title)


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
    """Route content to the appropriate create endpoint based on MIME type."""
    if not content_type:
        return "document"

    try:
        msg = EmailMessage()
        msg["content-type"] = content_type
        main_type = msg.get_content_type().lower()
        return "website" if main_type in SUPPORTED_WEB_MIME_TYPES else "document"
    except Exception:
        return "document"


async def _get_uncached_pages(
    content_hash: str,
    total_pages: int,
    extraction_cache: Cache,
    ai_config: ProcessorConfig,
) -> set[int]:
    """Pages without AI extraction cache."""
    assert ai_config.extraction_cache_prefix
    keys = [ai_config.extraction_cache_key(content_hash, idx) for idx in range(total_pages)]
    cached_keys = await extraction_cache.batch_exists(keys)
    cached_indices = {idx for idx, key in enumerate(keys) if key in cached_keys}
    return set(range(total_pages)) - cached_indices


def _validate_page_numbers(pages: list[int] | None, total_pages: int) -> None:
    if not pages:
        return
    invalid_pages = [p for p in pages if p < 0 or p >= total_pages]
    if invalid_pages:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid page numbers: {invalid_pages!r}. Document has {total_pages} pages (0-indexed).",
        )
