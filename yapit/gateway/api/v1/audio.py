from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from yapit.contracts import TTS_AUDIO_CACHE
from yapit.gateway.auth import authenticate
from yapit.gateway.deps import AudioCache, CurrentBlockVariant, RedisClient

router = APIRouter(prefix="/v1", tags=["audio"])


@router.get("/audio/{variant_hash}", dependencies=[Depends(authenticate)])
async def get_audio(
    variant: CurrentBlockVariant,
    redis: RedisClient,
    cache: AudioCache,
) -> Response:
    """Fetch cached audio for a block variant. Checks Redis first, falls back to SQLite."""
    audio_data = await redis.get(TTS_AUDIO_CACHE.format(hash=variant.hash))
    if audio_data is None:
        audio_data = await cache.retrieve_data(variant.hash)
    if audio_data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio not cached")

    return Response(
        content=audio_data,
        media_type="audio/ogg",
    )
