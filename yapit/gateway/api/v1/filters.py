from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

import re2 as re
from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlmodel import delete, select
from starlette.concurrency import run_in_threadpool

from yapit.contracts.redis_keys import (
    FILTER_CANCEL,
    FILTER_INFLIGHT,
    FILTER_STATUS,
)
from yapit.gateway.deps import AuthenticatedUser, CurrentDoc, DbSession, RedisClient, TextSplitterDep, get_doc
from yapit.gateway.domain_models import Block, Document, Filter, FilterConfig
from yapit.gateway.text_splitter import TextSplitter
from yapit.gateway.utils import estimate_duration_ms

# TODO admin-only endpoint to change preset filter rules

log = logging.getLogger("filters")
router = APIRouter(prefix="/v1", tags=["Filters"])

FILTER_LOCK_TTL = 300  # seconds – NX lock
FILTER_STATUS_TTL = 900  # seconds – queued/running
FILTER_DONE_TTL = 86_400  # keep "done/error" 24h for debugging
TRANSFORM_TIMEOUT_S = 120  # hard timeout for regex + LLM pass


class FilterJobRequest(BaseModel):
    """Requires at least one of filter_id/custom_config; if filter_id is set, drop custom_config."""

    filter_config: FilterConfig


class SimpleMessage(BaseModel):
    message: str


class FilterPresetRead(BaseModel):
    id: int
    name: str
    description: str | None
    config: dict[str, Any]


@router.post("/filters/validate", response_model=SimpleMessage)
def validate_regex(
    body: FilterJobRequest,
    _: AuthenticatedUser,
) -> SimpleMessage:
    for rule in (body.filter_config or {}).get("regex_rules", []):
        try:
            re.compile(rule["pattern"])
        except re.error as exc:
            raise HTTPException(422, f"Invalid regex: {exc}") from exc
    return SimpleMessage(message="ok")


@router.get("/filter_presets", response_model=list[FilterPresetRead])
async def list_filter_presets(
    db: DbSession,
    user: AuthenticatedUser,
) -> list[FilterPresetRead]:
    presets = (await db.exec(select(Filter).where(Filter.user_id == user.id or Filter.user_id is None))).all()
    return [FilterPresetRead(id=p.id, name=p.name, description=p.description, config=p.config) for p in presets]


@router.get(
    "/documents/{document_id}/filter_status",
    response_model=SimpleMessage,
    status_code=200,
)
async def filter_status(
    document_id: UUID,
    db: DbSession,
    redis: RedisClient,
    _: AuthenticatedUser,
) -> SimpleMessage:
    """Return current filter-pipeline state for `document_id` (none|pending|running|done|error).

    * primary source: Redis key  (while job is in flight or for 24 h after)
    * fallback      : DB row     (lets us answer after Redis TTL expired)
    """
    key = FILTER_STATUS.format(document_id=document_id)
    val: bytes | None = await redis.get(key)
    if val is not None:
        return SimpleMessage(message=val.decode())
    doc: Document = await get_doc(document_id, db=db)
    return SimpleMessage(message="done" if doc.filtered_text is not None else "none")


@router.post(
    "/documents/{document_id}/apply_filters",
    response_model=SimpleMessage,
    status_code=status.HTTP_202_ACCEPTED,
)
async def apply_filters(
    document_id: UUID,
    body: FilterJobRequest,
    bg: BackgroundTasks,
    _: CurrentDoc,
    redis: RedisClient,
    splitter: TextSplitterDep,
    __: AuthenticatedUser,
) -> SimpleMessage:
    """Kick off (re-)filtering job for a document."""
    if not await redis.set(FILTER_INFLIGHT.format(document_id=document_id), 1, nx=True, ex=FILTER_LOCK_TTL):
        raise HTTPException(409, "Filter job already in progress for this document.")

    await redis.set(FILTER_STATUS.format(document_id=document_id), "pending", ex=FILTER_STATUS_TTL)
    bg.add_task(_run_filter_job, document_id=document_id, config=body.filter_config, splitter=splitter, redis=redis)
    return SimpleMessage(message="Filtering job started.")


@router.post(
    "/documents/{document_id}/cancel_filter_job",
    response_model=SimpleMessage,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_filter_job(
    redis: RedisClient,
    document: CurrentDoc,
    _: AuthenticatedUser,
) -> SimpleMessage:
    """Cancel any in-progress filtering job and clear status."""
    await redis.set(FILTER_CANCEL.format(document_id=document.id), 1, ex=FILTER_LOCK_TTL)
    return SimpleMessage(message="Cancellation flag set.")


async def _run_filter_job(
    document_id: UUID,
    config: dict[str, Any],
    splitter: TextSplitter,
    redis: Redis,
    db: DbSession,
) -> None:
    status_key = FILTER_STATUS.format(document_id=document_id)
    cancel_key = FILTER_CANCEL.format(document_id=document_id)
    inflight_key = FILTER_INFLIGHT.format(document_id=document_id)

    try:
        await redis.set(status_key, "running", ex=FILTER_STATUS_TTL)

        doc = await get_doc(document_id, db)
        text = doc.original_text

        if await redis.exists(cancel_key):
            await redis.set(status_key, "cancelled", ex=600)
            return

        async def _transform(txt: str) -> str:
            for rule in config.get("regex_rules", []):
                txt = re.compile(rule["pattern"]).sub(rule.get("replacement", ""), txt)
            if config.get("llm"):
                # TODO build LLM prompt from config + OpenAI API request
                # TODO periodically check this (if parsing long docs in chunks (... stream progress?)
                if await redis.exists(cancel_key):
                    await redis.set(status_key, "cancelled", ex=FILTER_STATUS_TTL)
                    raise asyncio.CancelledError
                log.warning("LLM filter requested but not implemented – skipping")
            return txt

        try:
            text = await asyncio.wait_for(_transform(text), timeout=TRANSFORM_TIMEOUT_S)
        except asyncio.TimeoutError:
            raise RuntimeError(f"transform exceeded {TRANSFORM_TIMEOUT_S}s")

        # threadpool worth the overhead for hierarchical splitter or more complex
        text_blocks: list[str] = await run_in_threadpool(splitter.split, text=text)

        await db.exec(delete(Block).where(Block.document_id == document_id))  # replace old blocks
        db.add_all(
            [
                Block(document_id=document_id, idx=i, text=blk, est_duration_ms=estimate_duration_ms(blk))
                for i, blk in enumerate(text_blocks)
            ]
        )

        doc.filtered_text = text
        doc.last_applied_filter_config = config
        await db.commit()

        await redis.set(status_key, "done", ex=FILTER_DONE_TTL)
    except Exception as exc:
        log.exception(f"Error while filtering document {document_id}: {exc}")
        await redis.set(status_key, f"error:{exc}", ex=FILTER_DONE_TTL)
    finally:
        await redis.delete(inflight_key)
        await redis.delete(cancel_key)
