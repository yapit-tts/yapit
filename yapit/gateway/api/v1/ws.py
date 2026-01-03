import asyncio
import base64
import io
import json
import logging
import pickle
import uuid

import numpy as np
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from redis.asyncio import Redis
from sqlmodel import col, select

from yapit.contracts import (
    TTS_INFLIGHT,
    TTS_SUBSCRIBERS,
    SynthesisJob,
    SynthesisParameters,
    WSBlockStatus,
    WSCursorMoved,
    WSEvicted,
    WSSynthesizeRequest,
    get_pubsub_channel,
    get_queue_name,
)
from yapit.gateway.auth import authenticate_ws
from yapit.gateway.cache import Cache
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.deps import get_db_session
from yapit.gateway.domain_models import Block, BlockVariant, Document, TTSModel, UsageType, Voice
from yapit.gateway.exceptions import UsageLimitExceededError
from yapit.gateway.processors.tts.manager import TTSProcessorManager
from yapit.gateway.stack_auth.users import User
from yapit.gateway.usage import check_usage_limit

log = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


# HIGGS voice consistency: number of preceding blocks to use for context.
# 3 was found sufficient in manual testing (scripts/test_higgs_context_fixed.py)
CONTEXT_BUFFER_SIZE = 3


def _get_pending_key(user_id: str, document_id: uuid.UUID) -> str:
    """Redis key for tracking pending (queued) block indices per user/document."""
    return f"tts:pending:{user_id}:{document_id}"


async def _get_model_and_voice(db, model_slug: str, voice_slug: str) -> tuple[TTSModel, Voice]:
    """Fetch model and voice from DB."""
    model = (await db.exec(select(TTSModel).where(TTSModel.slug == model_slug))).first()
    if not model:
        raise ValueError(f"Model {model_slug!r} not found")

    voice = (await db.exec(select(Voice).where(Voice.slug == voice_slug, Voice.model_id == model.id))).first()
    if not voice:
        raise ValueError(f"Voice {voice_slug!r} not found for model {model_slug!r}")

    return model, voice


async def _build_context_tokens(
    db,
    cache: Cache,
    document_id: uuid.UUID,
    current_block_idx: int,
    model: TTSModel,
    voice: Voice,
    codec: str,
) -> str | None:
    """Build serialized context tokens from preceding blocks for HIGGS voice consistency."""
    if current_block_idx == 0:
        return None

    start_idx = max(0, current_block_idx - CONTEXT_BUFFER_SIZE)
    result = await db.exec(
        select(Block)
        .where(Block.document_id == document_id)
        .where(Block.idx >= start_idx)
        .where(Block.idx < current_block_idx)
        .order_by(Block.idx)
    )
    preceding_blocks = result.all()

    if not preceding_blocks:
        return None

    context_items: list[tuple[str, np.ndarray]] = []
    for blk in preceding_blocks:
        variant_hash = BlockVariant.get_hash(
            text=blk.text,
            model_slug=model.slug,
            voice_slug=voice.slug,
            codec=codec,
            parameters=voice.parameters,
        )
        token_data = await cache.retrieve_data(f"{variant_hash}:tokens")
        if token_data is None:
            continue
        b64_str = token_data.decode("utf-8")
        buffer = io.BytesIO(base64.b64decode(b64_str))
        arr = np.load(buffer, allow_pickle=False)
        context_items.append((blk.text, arr))

    if not context_items:
        return None

    buffer = io.BytesIO()
    pickle.dump(context_items, buffer)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


async def _queue_synthesis_job(
    db,
    redis: Redis,
    cache: Cache,
    processor_manager: TTSProcessorManager,
    settings: Settings,
    user: User,
    block: Block,
    model: TTSModel,
    voice: Voice,
) -> tuple[str, bool]:
    """Queue a synthesis job, returning (variant_hash, was_cached)."""
    served_codec = model.native_codec
    variant_hash = BlockVariant.get_hash(
        text=block.text,
        model_slug=model.slug,
        voice_slug=voice.slug,
        codec=served_codec,
        parameters=voice.parameters,
    )

    # Check if variant exists in DB
    variant: BlockVariant | None = (
        await db.exec(select(BlockVariant).where(BlockVariant.hash == variant_hash))
    ).first()

    # Check if audio is cached
    cached_data = await cache.retrieve_data(variant_hash)
    if cached_data is not None and variant is not None:
        # Link variant to this block if it exists for a different block
        if variant.block_id != block.id:
            await db.merge(
                BlockVariant(
                    hash=variant.hash,
                    block_id=block.id,
                    model_id=variant.model_id,
                    voice_id=variant.voice_id,
                    duration_ms=variant.duration_ms,
                    cache_ref=variant.cache_ref,
                )
            )
            await db.commit()
        return variant_hash, True

    # Create variant if it doesn't exist
    if variant is None:
        variant = BlockVariant(
            hash=variant_hash,
            block_id=block.id,
            model_id=model.id,
            voice_id=voice.id,
        )
        db.add(variant)
        await db.commit()

    # Track this block as subscriber to be notified when synthesis completes
    subscriber_key = TTS_SUBSCRIBERS.format(hash=variant_hash)
    subscriber_entry = f"{user.id}:{block.document_id}:{block.idx}"
    await redis.sadd(subscriber_key, subscriber_entry)
    await redis.expire(subscriber_key, 600)  # 10 min TTL

    # Check if already processing - if so, we're now subscribed and will be notified
    if await redis.exists(TTS_INFLIGHT.format(hash=variant_hash)):
        return variant_hash, False
    await redis.set(TTS_INFLIGHT.format(hash=variant_hash), 1, ex=300, nx=True)

    # Build context tokens for HIGGS voice consistency
    context_tokens = None
    if model.slug.startswith("higgs"):
        context_tokens = await _build_context_tokens(
            db=db,
            cache=cache,
            document_id=block.document_id,
            current_block_idx=block.idx,
            model=model,
            voice=voice,
            codec=served_codec,
        )

    job = SynthesisJob(
        job_id=uuid.uuid4(),
        variant_hash=variant_hash,
        user_id=user.id,
        document_id=block.document_id,
        block_idx=block.idx,
        synthesis_parameters=SynthesisParameters(
            model=model.slug,
            voice=voice.slug,
            text=block.text,
            kwargs=voice.parameters,
            codec=served_codec,
            context_tokens=context_tokens,
        ),
    )

    route = processor_manager.get_route(model.slug, "server")
    if route is None:
        raise ValueError(f"No server route for model {model.slug!r}")

    # Track pending (not yet cached) blocks for eviction before pushing to queue
    pending_key = _get_pending_key(user.id, block.document_id)
    await redis.sadd(pending_key, block.idx)
    await redis.expire(pending_key, 600)  # TTL 10 minutes

    queue_depth = await processor_manager.get_queue_depth(model.slug)
    threshold = settings.tts_overflow_queue_threshold

    if route.overflow and queue_depth > threshold:
        await route.overflow.process(job)  # serverless
    else:
        await redis.lpush(get_queue_name(model.slug), job.model_dump_json())  # route to primary queue

    return variant_hash, False


async def _handle_synthesize(
    ws: WebSocket,
    msg: WSSynthesizeRequest,
    user: User,
    redis: Redis,
    cache: Cache,
    processor_manager: TTSProcessorManager,
    settings: Settings,
):
    """Handle synthesize request - queue blocks for synthesis."""
    async for db in get_db_session(settings):
        # Validate document ownership
        doc = (await db.exec(select(Document).where(Document.id == msg.document_id))).first()
        if not doc or doc.user_id != user.id:
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

        # Usage limit check for server-side synthesis
        is_admin = bool(user.server_metadata and user.server_metadata.is_admin)
        if msg.synthesis_mode != "browser":
            usage_type = UsageType.server_kokoro if model.slug.startswith("kokoro") else UsageType.premium_voice
            total_chars = int(sum(len(b.text) for b in blocks) * model.usage_multiplier)
            try:
                await check_usage_limit(
                    user.id,
                    usage_type,
                    total_chars,
                    db,
                    is_admin=is_admin,
                    billing_enabled=settings.billing_enabled,
                )
            except UsageLimitExceededError as e:
                await ws.send_json({"type": "error", "error": str(e)})
                return

        # Queue each block
        for idx in msg.block_indices:
            block = block_map.get(idx)
            if not block:
                log.warning(f"Block {idx} not found in document {msg.document_id}")
                await ws.send_json(
                    WSBlockStatus(
                        document_id=msg.document_id,
                        block_idx=idx,
                        status="skipped",
                    ).model_dump(mode="json")
                )
                continue

            try:
                variant_hash, was_cached = await _queue_synthesis_job(
                    db, redis, cache, processor_manager, settings, user, block, model, voice
                )
                status = "cached" if was_cached else "queued"
                audio_url = f"/v1/audio/{variant_hash}" if was_cached else None

                await ws.send_json(
                    WSBlockStatus(
                        document_id=msg.document_id,
                        block_idx=idx,
                        status=status,
                        audio_url=audio_url,
                    ).model_dump(mode="json")
                )
            except Exception as e:
                log.error(f"Failed to queue block {idx}: {e}")
                await ws.send_json(
                    WSBlockStatus(
                        document_id=msg.document_id,
                        block_idx=idx,
                        status="error",
                        error=str(e),
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
    pending_key = _get_pending_key(user.id, msg.document_id)
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

    # Notify frontend
    await ws.send_json(
        WSEvicted(
            document_id=msg.document_id,
            block_indices=to_evict,
        ).model_dump(mode="json")
    )
    log.debug(f"Evicted {len(to_evict)} blocks outside window [{min_idx}, {max_idx}]")


async def _pubsub_listener(ws: WebSocket, redis: Redis, user_id: str):
    """Listen for pubsub messages and forward to WebSocket."""
    pubsub = redis.pubsub()
    channel = get_pubsub_channel(user_id)
    await pubsub.subscribe(channel)

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await ws.send_text(message["data"].decode())
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()


@router.websocket("/v1/ws/tts")
async def tts_websocket(
    ws: WebSocket,
    user: User = Depends(authenticate_ws),
    settings: Settings = Depends(get_settings),
):
    """WebSocket endpoint for TTS control."""
    redis: Redis = ws.app.state.redis_client
    cache: Cache = ws.app.state.audio_cache
    processor_manager: TTSProcessorManager = ws.app.state.tts_processor_manager

    await ws.accept()

    pubsub_task = asyncio.create_task(_pubsub_listener(ws, redis, user.id))

    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
                msg_type = data.get("type")

                if msg_type == "synthesize":
                    msg = WSSynthesizeRequest.model_validate(data)
                    await _handle_synthesize(ws, msg, user, redis, cache, processor_manager, settings)
                elif msg_type == "cursor_moved":
                    msg = WSCursorMoved.model_validate(data)
                    await _handle_cursor_moved(ws, msg, user, redis, settings)
                else:
                    await ws.send_json({"type": "error", "error": f"Unknown message type: {msg_type}"})

            except ValidationError as e:
                await ws.send_json({"type": "error", "error": str(e)})
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "error": "Invalid JSON"})

    except WebSocketDisconnect:
        log.info(f"WebSocket disconnected for user {user.id}")
    finally:
        pubsub_task.cancel()
        try:
            await pubsub_task
        except asyncio.CancelledError:
            pass
