import struct
import uuid
from typing import Annotated

import annotated_types
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import Base64Bytes, BaseModel
from sqlmodel import select

from yapit.gateway.auth import authenticate
from yapit.gateway.deps import (
    AudioCache,
    AuthenticatedUser,
    CurrentBlockVariant,
    DbSession,
    get_doc,
    get_model,
    get_voice,
)
from yapit.gateway.domain_models import Block, BlockVariant

router = APIRouter(prefix="/v1", tags=["audio"])

MAX_AUDIO_SIZE = 10 * 1024 * 1024  # 10MB


class AudioSubmitRequest(BaseModel):
    document_id: uuid.UUID
    block_idx: int
    model: str
    voice: str
    audio: Annotated[Base64Bytes, annotated_types.MaxLen(MAX_AUDIO_SIZE)]
    duration_ms: int


class AudioSubmitResponse(BaseModel):
    variant_hash: str
    audio_url: str


@router.get("/audio/{variant_hash}", dependencies=[Depends(authenticate)])
async def get_audio(
    variant: CurrentBlockVariant,
    cache: AudioCache,
) -> Response:
    """Fetch cached audio for a block variant."""
    audio_data = await cache.retrieve_data(variant.hash)
    if audio_data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio not cached")

    model = variant.model
    if model.native_codec == "pcm":
        audio_data = pcm_to_wav(audio_data, model.sample_rate, model.channels, model.sample_width)
        content_type = "audio/wav"
    else:
        content_type = f"audio/{model.native_codec}"

    return Response(
        content=audio_data,
        media_type=content_type,
    )


@router.post("/audio", dependencies=[Depends(authenticate)])
async def submit_audio(
    request: AudioSubmitRequest,
    user: AuthenticatedUser,
    db: DbSession,
    cache: AudioCache,
) -> AudioSubmitResponse:
    """Submit browser-synthesized audio for caching."""
    # Validate document ownership
    doc = await get_doc(request.document_id, db, user)

    # Get block by idx
    block = (await db.exec(select(Block).where(Block.document_id == doc.id, Block.idx == request.block_idx))).first()
    if not block:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Block not found")

    model = await get_model(db, request.model)
    voice = await get_voice(db, request.model, request.voice)

    variant_hash = BlockVariant.get_hash(
        text=block.text,
        model_slug=model.slug,
        voice_slug=voice.slug,
        codec=model.native_codec,
        parameters=voice.parameters,
    )
    variant = (await db.exec(select(BlockVariant).where(BlockVariant.hash == variant_hash))).first()
    if variant is None:
        variant = BlockVariant(
            hash=variant_hash,
            model_id=model.id,
            voice_id=voice.id,
            duration_ms=request.duration_ms,
        )
        db.add(variant)
    await db.commit()

    cache_ref = await cache.store(variant_hash, request.audio)
    if cache_ref is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to cache audio")

    variant.cache_ref = cache_ref
    await db.commit()

    return AudioSubmitResponse(
        variant_hash=variant_hash,
        audio_url=f"/v1/audio/{variant_hash}",
    )


def pcm_to_wav(pcm_data: bytes, sample_rate: int, channels: int, sample_width: int) -> bytes:
    """Wrap raw PCM bytes in a WAV header (44 bytes, lossless)."""
    # Add ~10ms of silence padding to prevent resampling artifacts at audio end
    silence_samples = sample_rate // 100  # ~10ms
    silence_bytes = b"\x00" * (silence_samples * channels * sample_width)
    pcm_data = pcm_data + silence_bytes

    data_size = len(pcm_data)
    bits_per_sample = sample_width * 8
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,  # fmt chunk size
        1,  # PCM format
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + pcm_data
