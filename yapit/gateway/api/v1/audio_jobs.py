from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, ValidationError

from yapit.gateway.audio_job import (
    AudioJobSpec,
    AudioJobState,
    AudioJobStatus,
    BlockRange,
    block_indices,
    cached_mask,
    cancel_job,
    daily_allowance,
    document_job,
    job_state,
    load_job,
    publish_job_state,
    start_job,
)
from yapit.gateway.auth import authenticate
from yapit.gateway.deps import (
    AudioCache,
    AuthenticatedUser,
    DbSession,
    RedisClient,
    SettingsDep,
    get_model,
    get_voice,
)
from yapit.gateway.domain_models import BlockVariant, Document
from yapit.gateway.synthesis import billed_characters, usage_type_for
from yapit.gateway.usage import (
    get_available_usage,
    get_effective_plan,
    get_limit_for_usage_type,
    get_user_subscription,
)

router = APIRouter(prefix="/v1/documents", tags=["Audio jobs"], dependencies=[Depends(authenticate)])


class AudioJobRequest(BaseModel):
    model: str
    voice: str
    ranges: list[BlockRange] = Field(min_length=1, max_length=1000)


class AudioJobEstimate(BaseModel):
    uncached_characters: list[int] = Field(
        description="Per audio block, the characters synthesizing it would count against the quota; 0 where cached"
    )
    plan_includes_voice: bool = Field(description="Whether the user's plan includes this voice's usage type at all")
    available_characters: int | None = Field(description="Characters left this period; None where unlimited")
    daily_blocks_left: int | None = Field(
        description="Blocks a job may still synthesize today; None where the quota bounds jobs instead"
    )
    running_job_document_id: UUID | None = Field(description="The document of the user's running job, if any")


@router.post("/{document_id}/audio-job", status_code=status.HTTP_201_CREATED)
async def start_audio_job(
    document_id: UUID,
    request: AudioJobRequest,
    user: AuthenticatedUser,
    db: DbSession,
    redis: RedisClient,
    cache: AudioCache,
) -> AudioJobState:
    """Synthesize the given block ranges of a document in the background, with no tab open."""
    doc = await _readable_document(db, document_id, user.id)
    model = await get_model(db, request.model)
    voice = await get_voice(db, request.model, request.voice)
    texts = _audio_texts(doc)
    for r in request.ranges:
        if r.first_block > r.last_block or r.last_block >= len(texts):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Range {r.title!r} ({r.first_block}-{r.last_block}) is not within the document's "
                f"{len(texts)} audio blocks",
            )

    blocks = block_indices(request.ranges)
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
    cached = await cached_mask(redis, cache, hashes)
    usage_type = usage_type_for(tts_model.slug)
    available, _ = await get_available_usage(user.id, usage_type, db, billing_enabled=settings.billing_enabled)
    plan = await get_effective_plan(await get_user_subscription(user.id, db), db)
    running = await load_job(redis, user.id)
    return AudioJobEstimate(
        uncached_characters=[0 if hit else billed_characters(text, tts_model) for text, hit in zip(texts, cached)],
        plan_includes_voice=not settings.billing_enabled or get_limit_for_usage_type(plan, usage_type) != 0,
        available_characters=available,
        daily_blocks_left=await daily_allowance(redis, db, settings, user.id, tts_model.slug),
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


async def _readable_document(db: DbSession, document_id: UUID, user_id: str) -> Document:
    doc = await db.get(Document, document_id)
    if doc is None or (doc.user_id != user_id and not doc.is_public):
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
