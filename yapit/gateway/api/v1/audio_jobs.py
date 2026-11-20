from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, ValidationError

from yapit.gateway.audio_job import (
    AudioJob,
    AudioJobSpec,
    AudioJobStatus,
    BlockRange,
    block_indices,
    cancel_job,
    count_cached,
    load_job,
    start_job,
    variant_hashes,
)
from yapit.gateway.auth import authenticate
from yapit.gateway.cache import Cache
from yapit.gateway.deps import AudioCache, AuthenticatedUser, DbSession, RedisClient, get_model, get_voice
from yapit.gateway.domain_models import Document

router = APIRouter(prefix="/v1/documents", tags=["Audio jobs"], dependencies=[Depends(authenticate)])


class AudioJobRequest(BaseModel):
    model: str
    voice: str
    ranges: list[BlockRange] = Field(min_length=1, max_length=1000)


class AudioJobResponse(BaseModel):
    document_id: UUID
    model: str
    voice: str
    ranges: list[BlockRange]
    status: AudioJobStatus
    error: str | None
    total_blocks: int
    cached_blocks: int


@router.post("/{document_id}/audio-job", status_code=status.HTTP_201_CREATED)
async def start_audio_job(
    document_id: UUID,
    request: AudioJobRequest,
    user: AuthenticatedUser,
    db: DbSession,
    redis: RedisClient,
    cache: AudioCache,
) -> AudioJobResponse:
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
    return await _response(job, redis, cache)


@router.get("/{document_id}/audio-job")
async def get_audio_job(
    document_id: UUID,
    user: AuthenticatedUser,
    db: DbSession,
    redis: RedisClient,
    cache: AudioCache,
) -> AudioJobResponse:
    """The document's audio job: its status, and how many of its blocks are cached."""
    await _readable_document(db, document_id, user.id)
    job = await _document_job(redis, user.id, document_id)
    return await _response(job, redis, cache)


@router.delete("/{document_id}/audio-job", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_audio_job(document_id: UUID, user: AuthenticatedUser, redis: RedisClient) -> Response:
    """Stop the document's audio job. Blocks a worker already took are finished and cached."""
    await _document_job(redis, user.id, document_id)
    await cancel_job(redis, user.id)
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


async def _document_job(redis: RedisClient, user_id: str, document_id: UUID) -> AudioJob:
    job = await load_job(redis, user_id)
    if job is None or job.spec.document_id != document_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No audio job for this document")
    return job


async def _response(job: AudioJob, redis: RedisClient, cache: Cache) -> AudioJobResponse:
    hashes = variant_hashes(job.spec)
    return AudioJobResponse(
        document_id=job.spec.document_id,
        model=job.spec.model,
        voice=job.spec.voice,
        ranges=job.spec.ranges,
        status=job.status,
        error=job.error,
        total_blocks=len(job.spec.blocks),
        cached_blocks=await count_cached(redis, cache, hashes),
    )
