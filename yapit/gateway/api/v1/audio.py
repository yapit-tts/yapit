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

    return Response(
        content=audio_data,
        media_type=f"audio/{variant.model.native_codec}",
        headers={
            "X-Audio-Codec": variant.model.native_codec,
            "X-Sample-Rate": str(variant.model.sample_rate),
            "X-Channels": str(variant.model.channels),
            "X-Sample-Width": str(variant.model.sample_width),
            "X-Duration-Ms": str(variant.duration_ms or 0),
        },
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
            block_id=block.id,
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
