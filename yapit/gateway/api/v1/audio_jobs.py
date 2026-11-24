import asyncio
import os
from collections.abc import Callable
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi import Path as PathParam
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError

from yapit.contracts import KOKORO_OPUS_BITRATE, OPENAI_TTS_OPUS_BITRATE
from yapit.gateway.audio_export import (
    ENCODINGS,
    AudioExportState,
    AudioNotCached,
    Chapter,
    ExportBusy,
    ExportFormat,
    ExportStore,
    request_export,
)
from yapit.gateway.audio_job import (
    AudioJobSpec,
    AudioJobState,
    AudioJobStatus,
    BlockRange,
    block_indices,
    cancel_job,
    document_job,
    job_state,
    load_job,
    prepared_mask,
    publish_job_state,
    start_job,
)
from yapit.gateway.auth import authenticate
from yapit.gateway.constants import estimate_duration_ms
from yapit.gateway.deps import (
    AudioCache,
    AuthenticatedUser,
    DbSession,
    NonGuestUser,
    RedisClient,
    SettingsDep,
    get_model,
    get_voice,
)
from yapit.gateway.domain_models import BlockVariant, Document, readable_by
from yapit.gateway.metrics import log_event
from yapit.gateway.synthesis import billed_characters, usage_type_for
from yapit.gateway.usage import (
    get_available_usage,
    get_effective_plan,
    get_limit_for_usage_type,
    get_user_subscription,
)

# A download holds its file from deletion, so a client that stops reading must not hold it for good
DOWNLOAD_MIN_BYTES_PER_S = 64 * 1024
DOWNLOAD_GRACE_S = 60


def _export_store(request: Request) -> ExportStore:
    return request.app.state.export_store


ExportStoreDep = Annotated[ExportStore, Depends(_export_store)]

router = APIRouter(prefix="/v1/documents", tags=["Audio jobs"], dependencies=[Depends(authenticate)])


class AudioJobRequest(BaseModel):
    model: str
    voice: str
    ranges: list[BlockRange] = Field(min_length=1, max_length=1000)


class AudioExportRequest(AudioJobRequest):
    format: ExportFormat


class AudioJobEstimate(BaseModel):
    uncached_characters: list[int] = Field(
        description="Per audio block, the characters synthesizing it would count against the quota; 0 where cached"
    )
    plan_includes_voice: bool = Field(description="Whether the user's plan includes this voice's usage type at all")
    available_characters: int | None = Field(description="Characters left this period; None where unlimited")
    running_job_document_id: UUID | None = Field(description="The document of the user's running job, if any")


@router.post("/{document_id}/audio-job", status_code=status.HTTP_201_CREATED)
async def start_audio_job(
    document_id: UUID,
    request: AudioJobRequest,
    user: AuthenticatedUser,
    db: DbSession,
    redis: RedisClient,
    cache: AudioCache,
    settings: SettingsDep,
) -> AudioJobState:
    """Synthesize the given block ranges of a document in the background, with no tab open."""
    doc = await _readable_document(db, document_id, user.id)
    model = await get_model(db, request.model)
    voice = await get_voice(db, request.model, request.voice)
    texts = _audio_texts(doc)
    _check_ranges(request.ranges, len(texts))

    blocks = block_indices(request.ranges)
    # The cache evicts least recently played first, so a selection larger than the cache would
    # evict its own first blocks before the last are synthesized.
    cap_mb = settings.audio_cache_config.max_size_mb
    bitrate = KOKORO_OPUS_BITRATE if model.slug.startswith("kokoro") else OPENAI_TTS_OPUS_BITRATE
    estimated_bytes = sum(estimate_duration_ms(len(texts[idx])) for idx in blocks) * bitrate // 8 // 1000
    if cap_mb is not None and estimated_bytes > cap_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"That is about {estimated_bytes // (1024 * 1024):,} MB of audio, more than the server's "
            f"{cap_mb:,} MB audio cache holds. Pick fewer sections.",
        )
    spec = AudioJobSpec(
        document_id=document_id,
        model=model.slug,
        voice=voice.slug,
        voice_parameters=voice.parameters,
        ranges=request.ranges,
        blocks=blocks,
        texts=[texts[idx] for idx in blocks],
    )
    if not await start_job(redis, user.id, spec):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An audio job of yours is already running")
    job = await load_job(redis, user.id)
    assert job is not None
    return await job_state(redis, cache, job)


@router.get("/{document_id}/audio-job")
async def get_audio_job(
    document_id: UUID,
    user: AuthenticatedUser,
    db: DbSession,
    redis: RedisClient,
    cache: AudioCache,
) -> AudioJobState | None:
    """The document's audio job: its status, and how many of its blocks are cached. None if it has none."""
    await _readable_document(db, document_id, user.id)
    job = await document_job(redis, user.id, document_id)
    return await job_state(redis, cache, job) if job else None


@router.get("/{document_id}/audio-job/estimate")
async def estimate_audio_job(
    document_id: UUID,
    model: str,
    voice: str,
    user: AuthenticatedUser,
    db: DbSession,
    redis: RedisClient,
    cache: AudioCache,
    settings: SettingsDep,
) -> AudioJobEstimate:
    """What a job over the document in this voice would cost, block by block, and what the user has left."""
    doc = await _readable_document(db, document_id, user.id)
    tts_model = await get_model(db, model)
    tts_voice = await get_voice(db, model, voice)
    texts = _audio_texts(doc)
    hashes = [
        BlockVariant.get_hash(
            text=text, model_slug=tts_model.slug, voice_slug=tts_voice.slug, parameters=tts_voice.parameters
        )
        for text in texts
    ]
    cached = await prepared_mask(redis, cache, hashes)
    usage_type = usage_type_for(tts_model.slug)
    available, _ = await get_available_usage(user.id, usage_type, db, billing_enabled=settings.billing_enabled)
    plan = await get_effective_plan(await get_user_subscription(user.id, db), db)
    running = await load_job(redis, user.id)
    return AudioJobEstimate(
        uncached_characters=[0 if hit else billed_characters(text, tts_model) for text, hit in zip(texts, cached)],
        plan_includes_voice=not settings.billing_enabled or get_limit_for_usage_type(plan, usage_type) != 0,
        available_characters=available,
        running_job_document_id=running.spec.document_id
        if running is not None and running.status == AudioJobStatus.running
        else None,
    )


@router.delete("/{document_id}/audio-job", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_audio_job(
    document_id: UUID, user: AuthenticatedUser, redis: RedisClient, cache: AudioCache
) -> Response:
    """Stop the document's audio job. Blocks a worker already took are finished and cached."""
    if await document_job(redis, user.id, document_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No audio job for this document")
    await cancel_job(redis, user.id)
    await publish_job_state(redis, cache, user.id, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{document_id}/audio-export")
async def export_audio(
    document_id: UUID,
    request: AudioExportRequest,
    user: NonGuestUser,
    db: DbSession,
    redis: RedisClient,
    cache: AudioCache,
    store: ExportStoreDep,
) -> AudioExportState:
    """Join the ranges' prepared audio into one file, a chapter per range.

    Status `ready`: the file is stored and can be fetched. `building`: the document's WebSocket
    channel hears an `audio_export` message when it is.
    """
    doc = await _readable_document(db, document_id, user.id)
    model = await get_model(db, request.model)
    voice = await get_voice(db, request.model, request.voice)
    texts = _audio_texts(doc)
    _check_ranges(request.ranges, len(texts))

    def variant_hash(idx: int) -> str:
        return BlockVariant.get_hash(
            text=texts[idx], model_slug=model.slug, voice_slug=voice.slug, parameters=voice.parameters
        )

    chapters = [
        Chapter(title=r.title, variant_hashes=[variant_hash(idx) for idx in range(r.first_block, r.last_block + 1)])
        for r in request.ranges
    ]
    try:
        return await request_export(
            redis,
            cache,
            store,
            user.id,
            document_id,
            request.format,
            chapters,
        )
    except AudioNotCached as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Generate the audio first: {e}")
    except ExportBusy:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An audio file of yours is being built. Download this one once it is done.",
        )


@router.get("/{document_id}/audio-export/{key}.{fmt}")
async def get_audio_export(
    document_id: UUID,
    key: Annotated[str, PathParam(pattern=r"^[0-9a-f]{64}$")],
    fmt: ExportFormat,
    user: NonGuestUser,
    db: DbSession,
    store: ExportStoreDep,
) -> FileResponse:
    """An exported file, by the key and format its export answered with; kept while it downloads, up to a deadline."""
    doc = await _readable_document(db, document_id, user.id)
    path = store.stored(key, fmt)
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="The server no longer has this audio file. Save it again."
        )
    return _HeldFileResponse(
        path,
        store.hold(path),
        stat_result=path.stat(),
        media_type=ENCODINGS[fmt].media_type,
        filename=f"{doc.title or 'Document'}.{fmt}",
    )


class _HeldFileResponse(FileResponse):
    """A download that lets its file go once it ends, or once DOWNLOAD_GRACE_S and DOWNLOAD_MIN_BYTES_PER_S pass.

    A download cut off at the deadline ends short of its Content-Length, which the client reads as a failure.
    """

    def __init__(self, path: Path, release: Callable[[], None], stat_result: os.stat_result, **kwargs) -> None:
        super().__init__(path, stat_result=stat_result, **kwargs)
        self.release = release
        self.size = stat_result.st_size
        self.deadline_s = DOWNLOAD_GRACE_S + stat_result.st_size / DOWNLOAD_MIN_BYTES_PER_S

    async def __call__(self, scope, receive, send) -> None:
        try:
            async with asyncio.timeout(self.deadline_s):
                await super().__call__(scope, receive, send)
        except TimeoutError:
            await log_event(
                "audio_export_download_cut_off", data={"bytes": self.size, "deadline_s": round(self.deadline_s)}
            )
        finally:
            self.release()


def _check_ranges(ranges: list[BlockRange], block_count: int) -> None:
    for r in ranges:
        if r.first_block > r.last_block or r.last_block >= block_count:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Range {r.title!r} ({r.first_block}-{r.last_block}) is not within the document's "
                f"{block_count} audio blocks",
            )


async def _readable_document(db: DbSession, document_id: UUID, user_id: str) -> Document:
    doc = await db.get(Document, document_id)
    if doc is None or not readable_by(user_id, doc.user_id, doc.is_public):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return doc


def _audio_texts(doc: Document) -> list[str]:
    try:
        return doc.audio_texts
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="This document was created with an older version and is no longer compatible. Please re-upload it.",
        )
