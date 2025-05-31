from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any
from uuid import UUID

import re2 as re
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlmodel import delete, select
from starlette.concurrency import run_in_threadpool

from yapit.contracts.redis_keys import (
    FILTER_CANCEL,
    FILTER_INFLIGHT,
    FILTER_STATUS,
)
from yapit.gateway.auth import authenticate
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.db import create_session
from yapit.gateway.deps import AuthenticatedUser, CurrentDoc, DbSession, RedisClient, SettingsDep, TextSplitterDep
from yapit.gateway.domain_models import Block, Document, Filter, FilterConfig
from yapit.gateway.text_splitter import TextSplitter
from yapit.gateway.utils import estimate_duration_ms

log = logging.getLogger("filters")
router = APIRouter(prefix="/v1", tags=["Filters"])

FILTER_LOCK_TTL = 300
FILTER_STATUS_TTL = 900
FILTER_DONE_TTL = 86_400
TRANSFORM_TIMEOUT_S = 120


class FilterJobRequest(BaseModel):
    filter_config: FilterConfig


class SimpleMessage(BaseModel):
    message: str


class FilterPresetRead(BaseModel):
    id: int
    name: str
    description: str | None
    config: dict[str, Any]


@router.post("/filters/validate", response_model=SimpleMessage, dependencies=[Depends(authenticate)])
def validate_regex(
    body: FilterJobRequest,
) -> SimpleMessage:
    for rule in (body.filter_config or FilterConfig()).regex_rules:
        try:
            re.compile(rule.pattern)
        except re.error as exc:
            raise HTTPException(422, f"Invalid regex: {exc}") from exc
    return SimpleMessage(message="ok")


@router.get("/filter_presets", response_model=list[FilterPresetRead])
async def list_filter_presets(
    db: DbSession,
    user: AuthenticatedUser,
) -> list[FilterPresetRead]:
    presets_query = select(Filter).where(
        (Filter.user_id == user.id) | (Filter.user_id == None)
    )  # Ensure correct OR condition
    presets = (await db.exec(presets_query)).all()
    return [
        FilterPresetRead(
            id=p.id,
            name=p.name,
            description=p.description,
            config=p.config.model_dump() if isinstance(p.config, FilterConfig) else p.config,
        )
        for p in presets
    ]


@router.get(
    "/documents/{document_id}/filter_status",
    response_model=SimpleMessage,
    status_code=200,
)
async def filter_status(
    document_id: UUID,
    doc: CurrentDoc,
    redis: RedisClient,
    # _: AuthenticatedUser,
) -> SimpleMessage:
    key = FILTER_STATUS.format(document_id=document_id)
    val: bytes | None = await redis.get(key)
    if val is not None:
        return SimpleMessage(message=val.decode())
    return SimpleMessage(message="done" if doc.filtered_text is not None else "none")


@router.post(
    "/documents/{document_id}/apply_filters",
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
    "/documents/{document_id}/cancel_filter_job",
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
            await redis_client.set(status_key, f"error:Unauthorized", ex=FILTER_DONE_TTL)
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
