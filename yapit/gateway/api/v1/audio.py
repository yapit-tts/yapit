from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from yapit.gateway.auth import authenticate
from yapit.gateway.deps import AudioCache, CurrentBlockVariant

router = APIRouter(prefix="/v1", tags=["audio"])


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
        media_type="audio/ogg",
    )
