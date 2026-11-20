"""Background audio jobs: synthesize a chosen set of a document's blocks with no tab open.

A job keeps at most SLICE_SIZE of its variants in the queue, so none waits past its in-flight
marker's lifetime. Each result for a variant a job awaits makes the result consumer push the job's
user onto AUDIO_JOB_WAKE; the feeder blocks on that list and queues the job's next blocks through
request_synthesis, behind listeners (background=True). A user has at most one running job.
"""

import asyncio
import datetime as dt
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from loguru import logger
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlmodel import select

from yapit.contracts import (
    AUDIO_JOB,
    AUDIO_JOB_AWAITED,
    AUDIO_JOB_DAILY,
    AUDIO_JOB_LOST,
    AUDIO_JOB_WAITERS,
    AUDIO_JOB_WAKE,
    AUDIO_JOBS_RUNNING,
    TTS_AUDIO_CACHE,
    TTS_INFLIGHT,
    TTS_JOBS,
    TTS_SUBSCRIBERS,
    get_pubsub_channel,
    get_queue_name,
)
from yapit.gateway.backoff import Backoff
from yapit.gateway.cache import Cache
from yapit.gateway.config import Settings
from yapit.gateway.db import create_session
from yapit.gateway.deps import get_model, get_voice
from yapit.gateway.domain_models import BlockVariant, Document
from yapit.gateway.exceptions import ResourceNotFoundError
from yapit.gateway.metrics import log_error
from yapit.gateway.synthesis import INFLIGHT_TTL_S, CachedResult, ErrorResult, request_synthesis, usage_type_for
from yapit.gateway.usage import get_available_usage

SLICE_SIZE = 16
STATE_TTL_S = 24 * 3600
# Backstop for a wake that never comes: a result lost with the gateway, or a marker that expired.
RECONCILE_INTERVAL_S = 60
MAX_WAKE_BATCH = 200


class AudioJobStatus(StrEnum):
    running = "running"
    done = "done"
    cancelled = "cancelled"
    usage_limit = "usage_limit"
    daily_limit = "daily_limit"
    failed = "failed"


class BlockRange(BaseModel):
    first_block: int = Field(ge=0)
    last_block: int = Field(ge=0)  # inclusive
    title: str = Field(max_length=500)


class AudioJobSpec(BaseModel):
    document_id: uuid.UUID
    model: str
    voice: str
    voice_parameters: dict
    ranges: list[BlockRange]
    blocks: list[int]  # audio block indices, ascending, each once
    texts: list[str]  # the text of each of blocks, so no step of the job parses the document again


@dataclass(frozen=True)
class AudioJob:
    spec: AudioJobSpec
    status: AudioJobStatus
    error: str | None


class AudioJobState(BaseModel):
    document_id: uuid.UUID
    model: str
    voice: str
    ranges: list[BlockRange]
    status: AudioJobStatus
    error: str | None
    total_blocks: int
    cached_blocks: int
    pending_blocks: list[int] = Field(description="The job's audio block indices whose audio is not cached yet")


class WSAudioJob(BaseModel):
    """The document's job as it stands, sent to the tabs its user has open on the document."""

    type: Literal["audio_job"] = "audio_job"
    document_id: uuid.UUID
    job: AudioJobState | None


def block_indices(ranges: list[BlockRange]) -> list[int]:
    return sorted({idx for r in ranges for idx in range(r.first_block, r.last_block + 1)})


def variant_hashes(spec: AudioJobSpec) -> list[str]:
    return [
        BlockVariant.get_hash(text=text, model_slug=spec.model, voice_slug=spec.voice, parameters=spec.voice_parameters)
        for text in spec.texts
    ]


async def cached_mask(redis: Redis, cache: Cache, hashes: list[str]) -> list[bool]:
    """Whether each variant's audio is cached, in the order of hashes."""
    async with redis.pipeline(transaction=False) as pipe:
        for h in hashes:
            pipe.exists(TTS_AUDIO_CACHE.format(hash=h))
        in_redis = await pipe.execute()
    in_cache = await cache.batch_exists([h for h, hot in zip(hashes, in_redis) if not hot])
    return [bool(hot) or h in in_cache for h, hot in zip(hashes, in_redis)]


async def job_state(redis: Redis, cache: Cache, job: AudioJob) -> AudioJobState:
    cached = await cached_mask(redis, cache, variant_hashes(job.spec))
    return AudioJobState(
        document_id=job.spec.document_id,
        model=job.spec.model,
        voice=job.spec.voice,
        ranges=job.spec.ranges,
        status=job.status,
        error=job.error,
        total_blocks=len(job.spec.blocks),
        cached_blocks=sum(cached),
        pending_blocks=[idx for idx, hit in zip(job.spec.blocks, cached) if not hit],
    )


async def document_job(redis: Redis, user_id: str, document_id: uuid.UUID) -> AudioJob | None:
    """The user's job, if it is over this document."""
    job = await load_job(redis, user_id)
    return job if job is not None and job.spec.document_id == document_id else None


async def publish_job_state(redis: Redis, cache: Cache, user_id: str, document_id: uuid.UUID) -> None:
    job = await document_job(redis, user_id, document_id)
    message = WSAudioJob(document_id=document_id, job=await job_state(redis, cache, job) if job else None)
    await redis.publish(get_pubsub_channel(user_id, document_id), message.model_dump_json())


async def start_job(redis: Redis, user_id: str, spec: AudioJobSpec) -> bool:
    """Record a running job and wake the feeder to queue its first slice. False if one already runs."""
    if not await redis.sadd(AUDIO_JOBS_RUNNING, user_id):
        return False
    job_key = AUDIO_JOB.format(user_id=user_id)
    async with redis.pipeline(transaction=True) as pipe:
        pipe.delete(job_key, AUDIO_JOB_AWAITED.format(user_id=user_id), AUDIO_JOB_LOST.format(user_id=user_id))
        pipe.hset(
            job_key,
            mapping={"spec": spec.model_dump_json(), "status": AudioJobStatus.running.value, "next": 0},
        )
        pipe.expire(job_key, STATE_TTL_S)
        pipe.lpush(AUDIO_JOB_WAKE, user_id)
        await pipe.execute()
    return True


async def load_job(redis: Redis, user_id: str) -> AudioJob | None:
    fields = await redis.hgetall(AUDIO_JOB.format(user_id=user_id))
    if not fields:
        return None
    error = fields.get(b"error")
    return AudioJob(
        spec=AudioJobSpec.model_validate_json(fields[b"spec"]),
        status=AudioJobStatus(fields[b"status"].decode()),
        error=error.decode() if error else None,
    )


async def cancel_job(redis: Redis, user_id: str) -> None:
    """Stop the job queueing, and take its queued blocks off the queue where no one else waits on them."""
    if not await _finish(redis, user_id, AudioJobStatus.cancelled):
        return
    job = await load_job(redis, user_id)
    if job is None:
        return
    awaited = await redis.hgetall(AUDIO_JOB_AWAITED.format(user_id=user_id))
    for variant_hash, entry in awaited.items():
        _, job_id = _parse_awaited(entry)
        await _withdraw(redis, user_id, job.spec.model, variant_hash.decode(), job_id)
    await redis.delete(AUDIO_JOB_AWAITED.format(user_id=user_id), AUDIO_JOB_LOST.format(user_id=user_id))


async def run_audio_job_feeder(redis: Redis, cache: Cache, settings: Settings) -> None:
    logger.info("Audio job feeder starting")

    backoff = Backoff()
    last_reconcile = 0.0
    while True:
        try:
            for user_id in await _collect_wakes(redis):
                await _feed_job_logged(redis, cache, settings, user_id)
            if time.monotonic() - last_reconcile >= RECONCILE_INTERVAL_S:
                await _reconcile(redis, cache, settings)
                last_reconcile = time.monotonic()
            backoff.reset()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"Audio job feeder error: {e}")
            await log_error(f"Audio job feeder error: {e}")
            await backoff.sleep()


async def top_up(redis: Redis, cache: Cache, settings: Settings, user_id: str) -> None:
    """Queue the job's next blocks until SLICE_SIZE of its variants are in flight."""
    if not await redis.sismember(AUDIO_JOBS_RUNNING, user_id):
        return
    job = await load_job(redis, user_id)
    if job is None:
        await redis.srem(AUDIO_JOBS_RUNNING, user_id)
        return
    spec = job.spec
    job_key = AUDIO_JOB.format(user_id=user_id)
    awaited_key = AUDIO_JOB_AWAITED.format(user_id=user_id)
    lost_key = AUDIO_JOB_LOST.format(user_id=user_id)
    await redis.expire(job_key, STATE_TTL_S)
    waiters_of = AUDIO_JOB_WAITERS.format
    next_position = int(await redis.hget(job_key, "next") or 0)

    async with create_session() as db:
        access = (
            await db.exec(select(Document.user_id, Document.is_public).where(Document.id == spec.document_id))
        ).first()
        if access is None or (access[0] != user_id and not access[1]):
            await _finish(redis, user_id, AudioJobStatus.failed, "The document is no longer available")
            return
        try:
            model = await get_model(db, spec.model)
            voice = await get_voice(db, spec.model, spec.voice)
        except ResourceNotFoundError as e:
            await _finish(redis, user_id, AudioJobStatus.failed, str(e))
            return

        allowance = await daily_allowance(redis, db, settings, user_id, model.slug)
        while await redis.hlen(awaited_key) < SLICE_SIZE:
            retried = await redis.lindex(lost_key, 0)
            position = int(retried) if retried is not None else next_position
            if position >= len(spec.blocks):
                break
            block_idx, text = spec.blocks[position], spec.texts[position]
            variant_hash = BlockVariant.get_hash(
                text=text, model_slug=model.slug, voice_slug=voice.slug, parameters=voice.parameters
            )
            if allowance is not None and allowance <= 0 and not await _is_cached(redis, cache, variant_hash):
                await _finish(redis, user_id, AudioJobStatus.daily_limit, "Daily limit for audio jobs reached")
                return
            if retried is not None:
                await redis.lpop(lost_key)
            else:
                next_position += 1
                await redis.hset(job_key, "next", next_position)
            if await redis.hexists(awaited_key, variant_hash):
                continue

            # Registered before the request, so a result that lands during it still wakes this job
            await redis.hset(awaited_key, variant_hash, f"{position}:")
            await redis.sadd(waiters_of(hash=variant_hash), user_id)
            await redis.expire(waiters_of(hash=variant_hash), STATE_TTL_S)
            result = await request_synthesis(
                db=db,
                redis=redis,
                cache=cache,
                user_id=user_id,
                text=text,
                model=model,
                voice=voice,
                billing_enabled=settings.billing_enabled,
                document_id=spec.document_id,
                block_idx=block_idx,
                track_for_websocket=False,
                background=True,
            )
            if isinstance(result, CachedResult | ErrorResult):
                await redis.hdel(awaited_key, variant_hash)
                await redis.srem(waiters_of(hash=variant_hash), user_id)
                if isinstance(result, ErrorResult):
                    await _finish(redis, user_id, AudioJobStatus.usage_limit, result.error)
                    return
                continue

            if result.job_id is not None:
                await redis.hset(awaited_key, variant_hash, f"{position}:{result.job_id}")
                # A result of another job for the variant may have cleared the waiters during the request
                await redis.sadd(waiters_of(hash=variant_hash), user_id)
                if allowance is not None:
                    await _count_daily(redis, user_id)
                    allowance -= 1
            if not await redis.sismember(AUDIO_JOBS_RUNNING, user_id):
                # Cancelled while this block was being queued, after the cancel swept the queue
                await _withdraw(redis, user_id, spec.model, variant_hash, result.job_id or "")
                return

    if next_position >= len(spec.blocks) and await redis.hlen(awaited_key) == 0 and await redis.llen(lost_key) == 0:
        await _finish(redis, user_id, AudioJobStatus.done)


async def _collect_wakes(redis: Redis) -> set[str]:
    result = await redis.brpop(AUDIO_JOB_WAKE, timeout=RECONCILE_INTERVAL_S)
    if result is None:
        return set()
    users = {result[1].decode()}
    while len(users) < MAX_WAKE_BATCH:
        raw = await redis.rpop(AUDIO_JOB_WAKE)
        if raw is None:
            break
        users.add(raw.decode())
    return users


async def _reconcile(redis: Redis, cache: Cache, settings: Settings) -> None:
    """Settle what no wake reported, then top up every running job.

    An awaited variant that is cached is forgotten. One whose job still waits in the queue gets its
    in-flight marker renewed, so a slow queue never outlives it. One with neither a queued job nor a
    marker was lost (with the gateway, or a worker), and goes back to the job to be queued again.
    """
    for raw_user in await redis.smembers(AUDIO_JOBS_RUNNING):
        user_id = raw_user.decode()
        awaited_key = AUDIO_JOB_AWAITED.format(user_id=user_id)
        for raw_hash, entry in (await redis.hgetall(awaited_key)).items():
            variant_hash = raw_hash.decode()
            position, job_id = _parse_awaited(entry)
            inflight_key = TTS_INFLIGHT.format(hash=variant_hash)
            if await _is_cached(redis, cache, variant_hash):
                await redis.hdel(awaited_key, variant_hash)
            elif job_id and await redis.hexists(TTS_JOBS, job_id):
                held = await redis.set(inflight_key, job_id, ex=INFLIGHT_TTL_S, nx=True)
                if not held and await redis.get(inflight_key) == job_id.encode():
                    await redis.expire(inflight_key, INFLIGHT_TTL_S)
            elif not await redis.exists(inflight_key):
                await redis.hdel(awaited_key, variant_hash)
                await redis.rpush(AUDIO_JOB_LOST.format(user_id=user_id), position)
        await _feed_job_logged(redis, cache, settings, user_id)


def _parse_awaited(entry: bytes) -> tuple[int, str]:
    """An awaited entry is "<position in spec.blocks>:<queued job id, empty if it joined another's>"."""
    position, job_id = entry.decode().split(":", 1)
    return int(position), job_id


async def _is_cached(redis: Redis, cache: Cache, variant_hash: str) -> bool:
    return bool(await redis.exists(TTS_AUDIO_CACHE.format(hash=variant_hash))) or await cache.exists(variant_hash)


async def feed_job(redis: Redis, cache: Cache, settings: Settings, user_id: str) -> None:
    """Top the job up, then tell its tabs where it stands.

    Every top-up follows a result the job awaited, or a reconcile, so it is when the job's progress changed.
    """
    await top_up(redis, cache, settings, user_id)
    job = await load_job(redis, user_id)
    if job is not None:
        await publish_job_state(redis, cache, user_id, job.spec.document_id)


async def _feed_job_logged(redis: Redis, cache: Cache, settings: Settings, user_id: str) -> None:
    """One job's failure is the next reconcile's to retry, not every other job's to wait on."""
    try:
        await feed_job(redis, cache, settings, user_id)
    except Exception as e:
        logger.bind(user_id=user_id).exception(f"Audio job top-up failed: {e}")
        await log_error(f"Audio job top-up failed: {e}", user_id=user_id)


async def daily_allowance(redis: Redis, db, settings: Settings, user_id: str, model_slug: str) -> int | None:
    """Blocks the job may still queue today; None where the usage check already bounds the job.

    The ceiling guards plans with unlimited usage for the model. Self-hosting (billing off) has none.
    """
    if not settings.billing_enabled:
        return None
    available, _ = await get_available_usage(user_id, usage_type_for(model_slug), db, billing_enabled=True)
    if available is not None:
        return None
    used = await redis.get(_daily_key(user_id))
    return settings.audio_job_daily_block_limit - int(used or 0)


async def _count_daily(redis: Redis, user_id: str) -> None:
    key = _daily_key(user_id)
    await redis.incr(key)
    await redis.expire(key, 2 * 24 * 3600)


def _daily_key(user_id: str) -> str:
    return AUDIO_JOB_DAILY.format(user_id=user_id, day=dt.datetime.now(dt.UTC).date().isoformat())


async def _finish(redis: Redis, user_id: str, status: AudioJobStatus, error: str | None = None) -> bool:
    """End a running job with this status. False if it had already ended."""
    if not await redis.srem(AUDIO_JOBS_RUNNING, user_id):
        return False
    job_key = AUDIO_JOB.format(user_id=user_id)
    await redis.hset(job_key, mapping={"status": status.value, "error": error or ""})
    await redis.expire(job_key, STATE_TTL_S)
    await redis.expire(AUDIO_JOB_AWAITED.format(user_id=user_id), STATE_TTL_S)
    logger.bind(user_id=user_id).info(f"Audio job ended: {status.value}")
    return True


# Takes a queued job block off the queue unless a listener or another audio job waits on its variant,
# or a worker already pulled it.
_WITHDRAW = """
redis.call('SREM', KEYS[5], ARGV[2])
if ARGV[1] == '' then return 0 end
if redis.call('SCARD', KEYS[4]) > 0 or redis.call('SCARD', KEYS[5]) > 0 then return 0 end
if redis.call('ZREM', KEYS[1], ARGV[1]) == 0 then return 0 end
redis.call('HDEL', KEYS[2], ARGV[1])
if redis.call('GET', KEYS[3]) == ARGV[1] then redis.call('DEL', KEYS[3]) end
return 1
"""


async def _withdraw(redis: Redis, user_id: str, model_slug: str, variant_hash: str, job_id: str) -> None:
    await redis.eval(
        _WITHDRAW,
        5,
        get_queue_name(model_slug),
        TTS_JOBS,
        TTS_INFLIGHT.format(hash=variant_hash),
        TTS_SUBSCRIBERS.format(hash=variant_hash),
        AUDIO_JOB_WAITERS.format(hash=variant_hash),
        job_id,
        user_id,
    )
