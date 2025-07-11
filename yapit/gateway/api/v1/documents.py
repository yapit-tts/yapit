import asyncio
import hashlib
import json
import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

import re2 as re
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field, HttpUrl
from redis.asyncio import Redis
from sqlmodel import delete, func, select
from starlette.concurrency import run_in_threadpool

from yapit.contracts import FILTER_CANCEL, FILTER_INFLIGHT, FILTER_STATUS
from yapit.gateway.config import Settings
from yapit.gateway.db import create_session
from yapit.gateway.deps import (
    AuthenticatedUser,
    CurrentDoc,
    DbSession,
    DocumentCache,
    RedisClient,
    SettingsDep,
    TextSplitterDep,
    get_doc,
)
from yapit.gateway.domain_models import Block, Document, DocumentType, FilterConfig
from yapit.gateway.text_splitter import TextSplitter
from yapit.gateway.utils import estimate_duration_ms

router = APIRouter(prefix="/v1/documents", tags=["Documents"])
log = logging.getLogger("filters")


# Filter job constants # TODO... we need to rehaul the filter system
FILTER_LOCK_TTL = 300
FILTER_STATUS_TTL = 900
FILTER_DONE_TTL = 86_400
TRANSFORM_TIMEOUT_S = 120


class TextDocumentCreateRequest(BaseModel):
    """Create a document from direct text input."""

    content: str = Field(min_length=1, strip_whitespace=True)


class PreparedDocumentCreateRequest(BaseModel):
    """Create a document from prepared content."""

    hash: str
    type: DocumentType | None = None  # Optional override of auto-detected type


class BlockRead(BaseModel):
    id: int
    idx: int
    text: str
    est_duration_ms: int | None = None


class DocumentCreateResponse(BaseModel):
    document_id: UUID
    title: str
    num_blocks: int
    est_duration_ms: int


class BlockPage(BaseModel):
    total: int
    items: list[BlockRead]
    next_offset: int | None


class DocumentPrepareRequest(BaseModel):
    url: HttpUrl


class DocumentPrepareResponse(BaseModel):
    hash: str  # Cache key for subsequent document creation
    type: DocumentType  # Always returns a type (defaults to website if unsure)
    size_mb: float

    pages: int | None = None  # for documents
    credits: int | None = None  # for documents
    title: str | None = None  # if available


@router.post("/prepare", response_model=DocumentPrepareResponse)
async def prepare_document(
    request: DocumentPrepareRequest,
    cache: DocumentCache,
    settings: SettingsDep,
    user: AuthenticatedUser,
) -> DocumentPrepareResponse:
    """Prepare a document from URL for creation.

    Downloads content, detects type, extracts metadata, and caches everything.
    Returns a hash to use for subsequent document creation.
    """
    cache_key = hashlib.sha256(str(request.url).encode()).hexdigest()
    cached_data = await cache.retrieve_data(cache_key)
    if cached_data:
        cached_info = json.loads(cached_data.decode())
        return DocumentPrepareResponse(**cached_info)

    # TODO: Implement actual downloading and type detection
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="URL preparation not yet implemented")


@router.post("/prepare/upload", response_model=DocumentPrepareResponse)
async def prepare_document_upload(
    file: UploadFile,
    cache: DocumentCache,
    settings: SettingsDep,
    user: AuthenticatedUser,
) -> DocumentPrepareResponse:
    """Prepare a document with type "document" from file upload. Accepts various document and image formats."""
    content = await file.read()

    content_hash = hashlib.sha256(content).hexdigest()
    cached_data = await cache.retrieve_data(content_hash)
    if cached_data:
        cached_info = json.loads(cached_data.decode())
        return DocumentPrepareResponse(**cached_info)

    # TODO: Extract metadata, detect pages, etc.
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="File upload preparation not yet implemented"
    )


async def _create_document_from_text(
    text: str,
    document_type: DocumentType,
    user_id: str,
    db: DbSession,
    splitter: TextSplitter,
    source_ref: str | None = None,
    title: str = "Untitled",
) -> DocumentCreateResponse:
    """Common logic for creating a document from text."""
    try:
        text_blocks = await run_in_threadpool(splitter.split, text=text)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Text splitting failed: {exc}"
        ) from exc

    doc = Document(
        user_id=user_id,
        title=title,
        type=document_type,
        source_ref=source_ref,
        original_text=text,
    )
    db.add(doc)

    est_total_ms = 0
    blocks: list[Block] = []
    for idx, text_block in enumerate(text_blocks):
        dur = estimate_duration_ms(text_block)
        est_total_ms += dur
        blocks.append(Block(document_id=doc.id, idx=idx, text=text_block, est_duration_ms=dur))
    db.add_all(blocks)
    await db.commit()

    return DocumentCreateResponse(
        document_id=doc.id,
        title=title,
        num_blocks=len(blocks),
        est_duration_ms=est_total_ms,
    )


@router.post("/text", response_model=DocumentCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_text_document(
    req: TextDocumentCreateRequest,
    db: DbSession,
    splitter: TextSplitterDep,
    user: AuthenticatedUser,
) -> DocumentCreateResponse:
    """Create a document from direct text input."""
    return await _create_document_from_text(
        text=req.content,  # Already validated and stripped by Pydantic
        document_type=DocumentType.text,
        user_id=user.id,
        db=db,
        splitter=splitter,
    )


@router.post("", response_model=DocumentCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_document(
    req: PreparedDocumentCreateRequest,
    db: DbSession,
    cache: DocumentCache,
    splitter: TextSplitterDep,
    user: AuthenticatedUser,
) -> DocumentCreateResponse:
    """Create a document from prepared content."""
    # TODO: Retrieve from cache and process based on type (web parsing vs document parsing) # TODO#2: Add doc parsing options / OCR options, ...
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Document creation from prepared content not yet implemented",
    )


@router.get("/{document_id}/blocks", response_model=BlockPage, dependencies=[Depends(get_doc)])
async def list_blocks(
    document_id: UUID,
    db: DbSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> BlockPage:
    total = (await db.exec(select(func.count()).select_from(Block).where(Block.document_id == document_id))).one()
    rows = await db.exec(
        select(Block).where(Block.document_id == document_id).order_by(Block.idx).offset(offset).limit(limit)
    )
    items = [BlockRead(id=b.id, idx=b.idx, text=b.text, est_duration_ms=b.est_duration_ms) for b in rows.all()]

    next_offset = offset + limit if offset + limit < total else None
    return BlockPage(total=total, items=items, next_offset=next_offset)


class DocumentMeta(BaseModel):
    document_id: UUID
    created: datetime
    has_filtered: bool
    last_applied_filter_config: dict | None


class FilterJobRequest(BaseModel):
    filter_config: FilterConfig


class SimpleMessage(BaseModel):
    message: str


@router.get("/{document_id}", response_model=DocumentMeta)
async def read_document_meta(doc: CurrentDoc) -> DocumentMeta:
    return DocumentMeta(
        document_id=doc.id,
        created=doc.created,
        has_filtered=doc.filtered_text is not None,
        last_applied_filter_config=doc.last_applied_filter_config,
    )


@router.get(
    "/{document_id}/filter-status",
    response_model=SimpleMessage,
    status_code=200,
)
async def filter_status(
    document_id: UUID,
    doc: CurrentDoc,
    redis: RedisClient,
) -> SimpleMessage:
    key = FILTER_STATUS.format(document_id=document_id)
    val: bytes | None = await redis.get(key)
    if val is not None:
        return SimpleMessage(message=val.decode())
    return SimpleMessage(message="done" if doc.filtered_text is not None else "none")


@router.post(
    "/{document_id}/apply-filters",
    response_model=SimpleMessage,
    status_code=status.HTTP_202_ACCEPTED,
)
async def apply_filters(
    document_id: UUID,
    request_body: FilterJobRequest,
    bg: BackgroundTasks,
    current_doc: CurrentDoc,
    redis: RedisClient,
    splitter: TextSplitterDep,
    user: AuthenticatedUser,
    resolved_settings_for_task: SettingsDep,
) -> SimpleMessage:
    if not await redis.set(FILTER_INFLIGHT.format(document_id=document_id), 1, nx=True, ex=FILTER_LOCK_TTL):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Filter job already in progress for this document.",
        )

    await redis.set(FILTER_STATUS.format(document_id=document_id), "pending", ex=FILTER_STATUS_TTL)
    bg.add_task(
        _run_filter_job,
        document_id=document_id,
        config=request_body.filter_config,
        splitter=splitter,
        redis_client=redis,
        passed_settings=resolved_settings_for_task,
        user_id=user.id,
    )
    return SimpleMessage(message="Filtering job started.")


@router.post(
    "/{document_id}/cancel-filter",
    response_model=SimpleMessage,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_filter_job(
    redis: RedisClient,
    document: CurrentDoc,
) -> SimpleMessage:
    await redis.set(FILTER_CANCEL.format(document_id=document.id), 1, ex=FILTER_LOCK_TTL)
    return SimpleMessage(message="Cancellation flag set.")


async def _run_filter_job(
    document_id: UUID,
    config: FilterConfig,
    splitter: TextSplitter,
    redis_client: Redis,
    passed_settings: Settings,
    user_id: str,
) -> None:
    status_key = FILTER_STATUS.format(document_id=document_id)
    cancel_key = FILTER_CANCEL.format(document_id=document_id)
    inflight_key = FILTER_INFLIGHT.format(document_id=document_id)

    db_session_context = create_session(passed_settings)
    db = await anext(db_session_context)

    try:
        await redis_client.set(status_key, "running", ex=FILTER_STATUS_TTL)

        doc: Document | None = await db.get(Document, document_id)
        if not doc:
            log.error(f"Document {document_id} not found in _run_filter_job")
            await redis_client.set(status_key, "error:Document not found", ex=FILTER_DONE_TTL)
            return
        if doc.user_id != user_id:
            log.error(f"User {user_id} unauthorized for document {document_id} in _run_filter_job")
            await redis_client.set(status_key, "error:Unauthorized", ex=FILTER_DONE_TTL)
            return

        text_to_filter = doc.original_text

        if await redis_client.exists(cancel_key):
            await redis_client.set(status_key, "cancelled", ex=600)
            log.info(f"Filter job for document {document_id} cancelled before transform.")
            return

        async def _transform(current_text: str) -> str:
            for rule in config.regex_rules:
                if await redis_client.exists(cancel_key):
                    raise asyncio.CancelledError
                current_text = re.compile(rule.pattern).sub(rule.replacement, current_text)

            if config.llm:
                if await redis_client.exists(cancel_key):
                    raise asyncio.CancelledError
                log.warning("LLM filter requested but not implemented – skipping")
            return current_text

        try:
            filtered_text = await asyncio.wait_for(_transform(text_to_filter), timeout=TRANSFORM_TIMEOUT_S)
        except asyncio.CancelledError:
            log.info(f"Filter job for document {document_id} was cancelled during transform.")
            await redis_client.set(status_key, "cancelled", ex=600)
            return
        except asyncio.TimeoutError:
            log.error(f"Transform for document {document_id} exceeded {TRANSFORM_TIMEOUT_S}s")
            await redis_client.set(status_key, "error:Transform timeout", ex=FILTER_DONE_TTL)
            return

        if await redis_client.exists(cancel_key):  # Check after transform, before DB ops
            await redis_client.set(status_key, "cancelled", ex=600)
            log.info(f"Filter job for document {document_id} cancelled after transform.")
            return

        text_blocks: list[str] = await run_in_threadpool(splitter.split, text=filtered_text)

        await db.exec(delete(Block).where(Block.document_id == document_id))
        new_blocks = [
            Block(document_id=document_id, idx=i, text=blk, est_duration_ms=estimate_duration_ms(blk))
            for i, blk in enumerate(text_blocks)
        ]
        db.add_all(new_blocks)

        doc.filtered_text = filtered_text
        doc.last_applied_filter_config = config.model_dump()
        await db.commit()

        await redis_client.set(status_key, "done", ex=FILTER_DONE_TTL)
    except asyncio.CancelledError:
        log.info(f"Filter job for document {document_id} was cancelled.")
        if (await redis_client.get(status_key) or b"").decode() != "cancelled":
            await redis_client.set(status_key, "cancelled", ex=600)
    except Exception as exc:
        log.exception(f"Error while filtering document {document_id}: {exc}")
        await redis_client.set(status_key, f"error:{str(exc)[:100]}", ex=FILTER_DONE_TTL)
    finally:
        await db.close()
        await redis_client.delete(inflight_key)
        await redis_client.delete(cancel_key)
