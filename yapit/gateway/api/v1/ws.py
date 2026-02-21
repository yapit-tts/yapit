import asyncio
import json
import time
import uuid
from typing import Literal, cast

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis
from sqlmodel import col, select
from starlette.applications import Starlette

from yapit.contracts import (
    MAX_TTS_REQUESTS_PER_MINUTE,
    RATELIMIT_TTS,
    TTS_INFLIGHT,
    TTS_JOB_INDEX,
    TTS_JOBS,
    TTS_PENDING,
    SynthesisJob,
    get_pubsub_channel,
    get_queue_name,
)
from yapit.gateway.auth import authenticate_ws
from yapit.gateway.cache import Cache
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.deps import get_db_session
from yapit.gateway.domain_models import Block, Document, TTSModel, Voice
from yapit.gateway.metrics import log_error, log_event
from yapit.gateway.stack_auth.users import User
from yapit.gateway.synthesis import ErrorResult, request_synthesis

router = APIRouter(tags=["websocket"])

BlockStatus = Literal["queued", "processing", "cached", "skipped", "error"]


class WSSynthesizeRequest(BaseModel):
    type: Literal["synthesize"] = "synthesize"
    document_id: uuid.UUID
    block_indices: list[int]
    model: str
    voice: str


class WSCursorMoved(BaseModel):
    type: Literal["cursor_moved"] = "cursor_moved"
    document_id: uuid.UUID
    cursor: int


class WSBlockStatus(BaseModel):
    type: Literal["status"] = "status"
    document_id: uuid.UUID
    block_idx: int
    status: BlockStatus
    audio_url: str | None = None
    error: str | None = None
    recoverable: bool = True
    model_slug: str | None = None
    voice_slug: str | None = None


class WSEvicted(BaseModel):
    type: Literal["evicted"] = "evicted"
    document_id: uuid.UUID
    block_indices: list[int]


@router.websocket("/v1/ws/tts")
async def tts_websocket(
    ws: WebSocket,
    user: User = Depends(authenticate_ws),
    settings: Settings = Depends(get_settings),
):
    """WebSocket endpoint for TTS control."""
    app = cast(Starlette, ws.app)
    redis: Redis = app.state.redis_client
    cache: Cache = app.state.audio_cache

    await ws.accept()
    ws_log = logger.bind(user_id=user.id)
    connect_time = time.time()
    await log_event("ws_connect", user_id=user.id)

    pubsub = redis.pubsub()
    subscribed_docs: set[str] = set()
    pubsub_task: asyncio.Task | None = None

    async def ensure_doc_subscribed(document_id: uuid.UUID) -> None:
        nonlocal pubsub_task
        doc_str = str(document_id)
        if doc_str not in subscribed_docs:
            await pubsub.subscribe(get_pubsub_channel(user.id, doc_str))
            subscribed_docs.add(doc_str)
            # Start listener after first subscription so listen() blocks properly
            if pubsub_task is None:
                pubsub_task = asyncio.create_task(_pubsub_listener(ws, pubsub))

    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
                msg_type = data.get("type")

                if msg_type == "synthesize":
                    msg = WSSynthesizeRequest.model_validate(data)
                    await ensure_doc_subscribed(msg.document_id)
                    await _handle_synthesize(ws, msg, user, redis, cache, settings)
                elif msg_type == "cursor_moved":
                    msg = WSCursorMoved.model_validate(data)
                    await _handle_cursor_moved(ws, msg, user, redis)
                else:
                    await ws.send_json({"type": "error", "error": f"Unknown message type: {msg_type}"})

            except ValidationError as e:
                ws_log.error(f"WS validation error: {e}")
                await ws.send_json({"type": "error", "error": str(e)})
            except json.JSONDecodeError:
                ws_log.error("WS invalid JSON")
                await ws.send_json({"type": "error", "error": "Invalid JSON"})
            except Exception as e:
                ws_log.exception(f"Unexpected error handling WS message: {e}")
                await log_error(f"WS message handling error: {e}", user_id=user.id)
                try:
                    await ws.send_json({"type": "error", "error": "Internal server error"})
                except Exception:
                    pass

    except WebSocketDisconnect:
        session_duration_ms = int((time.time() - connect_time) * 1000)
        await log_event("ws_disconnect", user_id=user.id, data={"session_duration_ms": session_duration_ms})
        ws_log.info(f"WebSocket disconnected after {session_duration_ms}ms")
    finally:
        if pubsub_task is not None:
            pubsub_task.cancel()
            try:
                await pubsub_task
            except asyncio.CancelledError:
                pass
        await pubsub.close()


async def _get_model_and_voice(db, model_slug: str, voice_slug: str) -> tuple[TTSModel, Voice]:
    model = (await db.exec(select(TTSModel).where(TTSModel.slug == model_slug))).first()
    if not model:
        raise ValueError(f"Model {model_slug!r} not found")

    voice = (await db.exec(select(Voice).where(Voice.slug == voice_slug, Voice.model_id == model.id))).first()
    if not voice:
        raise ValueError(f"Voice {voice_slug!r} not found for model {model_slug!r}")

    return model, voice


async def _handle_synthesize(
    ws: WebSocket,
    msg: WSSynthesizeRequest,
    user: User,
    redis: Redis,
    cache: Cache,
    settings: Settings,
):
    """Handle synthesize request - queue blocks for synthesis."""
    # Rate limit TTS requests per user (protects unlimited Kokoro from flooding)
    rate_key = RATELIMIT_TTS.format(user_id=user.id)
    count = await redis.incr(rate_key)
    if count == 1:
        await redis.expire(rate_key, 60)
    if count > MAX_TTS_REQUESTS_PER_MINUTE:
        await ws.send_json({"type": "error", "error": "Rate limit exceeded. Please slow down."})
        return

    async for db in get_db_session(settings):
        # Validate document ownership
        doc = (await db.exec(select(Document).where(Document.id == msg.document_id))).first()
        if not doc or (doc.user_id != user.id and not doc.is_public):
            await ws.send_json({"type": "error", "error": "Document not found or access denied"})
            return

        try:
            model, voice = await _get_model_and_voice(db, msg.model, msg.voice)
        except ValueError as e:
            await ws.send_json({"type": "error", "error": str(e)})
            return

        blocks = (
            await db.exec(
                select(Block).where(Block.document_id == msg.document_id).where(col(Block.idx).in_(msg.block_indices))
            )
        ).all()

        block_map = {b.idx: b for b in blocks}

        for idx in msg.block_indices:
            block = block_map.get(idx)
            if not block:
                logger.bind(user_id=user.id, document_id=str(msg.document_id)).warning(f"Block {idx} not found")
                await ws.send_json(
                    WSBlockStatus(
                        document_id=msg.document_id,
                        block_idx=idx,
                        status="skipped",
                        model_slug=model.slug,
                        voice_slug=voice.slug,
                    ).model_dump(mode="json")
                )
                continue

            try:
                result = await request_synthesis(
                    db=db,
                    redis=redis,
                    cache=cache,
                    user_id=user.id,
                    text=block.text,
                    model=model,
                    voice=voice,
                    billing_enabled=settings.billing_enabled,
                    document_id=msg.document_id,
                    block_idx=idx,
                    track_for_websocket=True,
                )

                await ws.send_json(
                    WSBlockStatus(
                        document_id=msg.document_id,
                        block_idx=idx,
                        status=result.status,
                        audio_url=result.audio_url,
                        error=getattr(result, "error", None),
                        recoverable=not isinstance(result, ErrorResult),
                        model_slug=model.slug,
                        voice_slug=voice.slug,
                    ).model_dump(mode="json")
                )
            except Exception as e:
                logger.bind(user_id=user.id, document_id=str(msg.document_id)).exception(
                    f"Failed to process block {idx}: {e}"
                )
                await log_error(f"Block processing error: {e}", user_id=user.id, block_idx=idx)
                await ws.send_json(
                    WSBlockStatus(
                        document_id=msg.document_id,
                        block_idx=idx,
                        status="error",
                        error="Internal server error",
                        model_slug=model.slug,
                        voice_slug=voice.slug,
                    ).model_dump(mode="json")
                )
        break


async def _handle_cursor_moved(
    ws: WebSocket,
    msg: WSCursorMoved,
    user: User,
    redis: Redis,
):
    """Handle cursor_moved - evict all pending blocks.

    The frontend cancels its own promises before sending cursor_moved,
    then re-requests exactly what it needs via the next synthesize message.
    """
    pending_key = TTS_PENDING.format(user_id=user.id, document_id=msg.document_id)
    pending_indices = await redis.smembers(pending_key)

    if not pending_indices:
        return

    to_evict = [int(idx_bytes) for idx_bytes in pending_indices]

    # Remove from pending set
    await redis.srem(pending_key, *pending_indices)

    # Remove jobs from queue for each evicted block
    for idx in to_evict:
        index_key = f"{user.id}:{msg.document_id}:{idx}"
        job_id = await redis.hget(TTS_JOB_INDEX, index_key)
        if job_id is None:
            continue

        job_id_str = job_id.decode()

        job_wrapper = await redis.hget(TTS_JOBS, job_id_str)
        if job_wrapper is not None:
            wrapper = json.loads(job_wrapper)
            job = SynthesisJob.model_validate_json(wrapper["job"])
            queue_name = get_queue_name(job.model_slug)
            removed_from_queue = await redis.zrem(queue_name, job_id_str)
            await redis.hdel(TTS_JOBS, job_id_str)

            # If the job was still in the queue (not yet pulled by a worker),
            # clean up the inflight semaphore — otherwise future requests for
            # the same variant see "already processing" but nobody is.
            if removed_from_queue:
                inflight_key = TTS_INFLIGHT.format(hash=job.variant_hash)
                inflight_owner = await redis.get(inflight_key)
                if inflight_owner and inflight_owner.decode() == job_id_str:
                    await redis.delete(inflight_key)

        await redis.hdel(TTS_JOB_INDEX, index_key)

    # Notify frontend
    await ws.send_json(
        WSEvicted(
            document_id=msg.document_id,
            block_indices=to_evict,
        ).model_dump(mode="json")
    )


async def _pubsub_listener(ws: WebSocket, pubsub):
    """Listen for pubsub messages and forward to WebSocket.

    Restarts on transient errors (Redis disconnect, encoding issues).
    Only stops on WebSocket disconnect — the main loop handles that lifecycle.
    """
    while True:
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    await ws.send_text(message["data"].decode())
        except WebSocketDisconnect:
            return
        except Exception:
            logger.exception("Pubsub listener error, restarting in 1s")
            await asyncio.sleep(1)
