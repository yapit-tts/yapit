import struct

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
