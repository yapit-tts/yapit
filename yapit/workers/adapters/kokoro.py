import asyncio
import io
import json
import os
from pathlib import Path
from typing import Unpack

import av
import numpy as np
import torch
from kokoro import KPipeline
from typing_extensions import TypedDict

from yapit.workers.adapters.base import SynthAdapter

DEVICE: str = os.getenv("DEVICE", "")

KOKORO_SAMPLE_RATE = 24_000
OPUS_BITRATE = 48_000


class VoiceConfig(TypedDict):
    voice: str
    speed: float


class KokoroAdapter(SynthAdapter[VoiceConfig]):
    def __init__(self):
        if not DEVICE:
            raise ValueError("DEVICE environment variable must be set to 'cpu' or 'cuda'")
        if DEVICE == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but unavailable, please check your setup.")
        self._pipe: KPipeline | None = None
        self._voices: list[str] = []
        self._lock = asyncio.Lock()
        self._last_duration_ms: int = 0

    @property
    def pipe(self) -> KPipeline:
        if self._pipe is None:
            raise RuntimeError("Adapter not initialized. Call initialize() first.")
        return self._pipe

    async def initialize(self) -> None:
        if self._pipe is not None:
            return
        self._pipe = KPipeline(repo_id="hexgrad/Kokoro-82M", lang_code="a", device=DEVICE)
        voices_json = Path(__file__).parent.parent / "kokoro" / "voices.json"
        self._voices = [v["index"] for v in json.load(open(voices_json))]
        for v in self._voices:
            self.pipe.load_voice(v)

    async def synthesize(self, text: str, **kwargs: Unpack[VoiceConfig]) -> bytes:
        async with self._lock:  # model not thread-safe (usage as local worker with fastapi)
            pcm = b"".join(
                [
                    (audio.numpy() * 32767).astype(np.int16).tobytes()  # scale [-1, 1] f32 tensor to int16 range
                    for _, _, audio in self._pipe(text, voice=kwargs["voice"], speed=kwargs["speed"])
                    if audio is not None
                ]
            )

        # Calculate exact duration from PCM before lossy encoding
        self._last_duration_ms = int(len(pcm) / (KOKORO_SAMPLE_RATE * 2) * 1000)

        return _pcm_to_ogg_opus(pcm)

    def calculate_duration_ms(self, audio_bytes: bytes) -> int:
        return self._last_duration_ms


def _pcm_to_ogg_opus(pcm_bytes: bytes) -> bytes:
    """Encode raw 24kHz mono int16 PCM to OGG_OPUS."""
    buf = io.BytesIO()
    output = av.open(buf, "w", format="ogg")
    stream = output.add_stream("libopus", rate=KOKORO_SAMPLE_RATE)
    stream.bit_rate = OPUS_BITRATE

    samples = np.frombuffer(pcm_bytes, dtype=np.int16)
    frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
    frame.sample_rate = KOKORO_SAMPLE_RATE

    for packet in stream.encode(frame):
        output.mux(packet)
    for packet in stream.encode(None):
        output.mux(packet)
    output.close()

    return buf.getvalue()
