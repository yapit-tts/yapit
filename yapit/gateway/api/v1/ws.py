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
from yapit.gateway.metrics import log_event
from yapit.gateway.stack_auth.users import User
from yapit.gateway.synthesis import request_synthesis

router = APIRouter(tags=["websocket"])

SynthesisMode = Literal["browser", "server"]
BlockStatus = Literal["queued", "processing", "cached", "skipped", "error"]


class WSSynthesizeRequest(BaseModel):
    type: Literal["synthesize"] = "synthesize"
    document_id: uuid.UUID
    block_indices: list[int]
    cursor: int
    model: str
    voice: str
    synthesis_mode: SynthesisMode


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
                    await _handle_cursor_moved(ws, msg, user, redis, settings)
                else:
                    await ws.send_json({"type": "error", "error": f"Unknown message type: {msg_type}"})

            except ValidationError as e:
                logger.error(f"WS validation error from user {user.id}: {e}")
                await ws.send_json({"type": "error", "error": str(e)})
            except json.JSONDecodeError:
                logger.error(f"WS invalid JSON from user {user.id}")
                await ws.send_json({"type": "error", "error": "Invalid JSON"})
            except Exception as e:
                logger.exception(f"Unexpected error handling WS message from user {user.id}: {e}")
                try:
                    await ws.send_json({"type": "error", "error": "Internal server error"})
                except Exception:
                    pass

    except WebSocketDisconnect:
        session_duration_ms = int((time.time() - connect_time) * 1000)
        await log_event("ws_disconnect", user_id=user.id, data={"session_duration_ms": session_duration_ms})
        logger.info(f"WebSocket disconnected for user {user.id} after {session_duration_ms}ms")
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
                logger.warning(f"Block {idx} not found in document {msg.document_id}")
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
                    synthesis_mode=msg.synthesis_mode,
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
                        model_slug=model.slug,
                        voice_slug=voice.slug,
                    ).model_dump(mode="json")
                )
            except Exception as e:
                logger.error(f"Failed to process block {idx}: {e}")
                await ws.send_json(
                    WSBlockStatus(
                        document_id=msg.document_id,
                        block_idx=idx,
                        status="error",
                        error=str(e),
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
    settings: Settings,
):
    """Handle cursor_moved - evict blocks outside the buffer window."""
    pending_key = TTS_PENDING.format(user_id=user.id, document_id=msg.document_id)
    pending_indices = await redis.smembers(pending_key)

    if not pending_indices:
        return

    # Calculate eviction window
    min_idx = msg.cursor - settings.tts_buffer_behind
    max_idx = msg.cursor + settings.tts_buffer_ahead

    # Find indices to evict (outside window)
    to_evict = []
    for idx_bytes in pending_indices:
        idx = int(idx_bytes)
        if idx < min_idx or idx > max_idx:
            to_evict.append(idx)

    if not to_evict:
        return

    # Remove from pending set
    await redis.srem(pending_key, *to_evict)

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
            await redis.zrem(queue_name, job_id_str)
            await redis.hdel(TTS_JOBS, job_id_str)

        await redis.hdel(TTS_JOB_INDEX, index_key)

    await log_event(
        "eviction_triggered",
        user_id=user.id,
        document_id=str(msg.document_id),
        data={
            "cursor": msg.cursor,
            "window": [min_idx, max_idx],
            "evicted_indices": to_evict,
            "evicted_count": len(to_evict),
        },
    )

    # Notify frontend
    await ws.send_json(
        WSEvicted(
            document_id=msg.document_id,
            block_indices=to_evict,
        ).model_dump(mode="json")
    )
    logger.debug(f"Evicted {len(to_evict)} blocks outside window [{min_idx}, {max_idx}]")


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
