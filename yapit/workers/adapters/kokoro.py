import asyncio
import json
import os
from pathlib import Path
from typing import Unpack

import numpy as np
import torch
from kokoro import KPipeline
from typing_extensions import TypedDict

from yapit.workers.adapters.base import SynthAdapter

DEVICE: str = os.getenv("DEVICE", "")


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
        pcm_chunks = []
        async with self._lock:  # model not thread-safe (usage as local worker with fastapi)
            for _, _, audio in self.pipe(text, voice=kwargs["voice"], speed=kwargs["speed"]):
                if audio is None:
                    continue
                pcm = (audio.numpy() * 32767).astype(np.int16).tobytes()  # scale [-1, 1] f32 tensor to int16 range
                pcm_chunks.append(pcm)
        return b"".join(pcm_chunks)

    def calculate_duration_ms(self, audio_bytes: bytes) -> int:
        """Calculate audio duration for Kokoro's 24kHz mono 16-bit PCM format."""
        # Kokoro outputs: 24000 Hz, 1 channel, 2 bytes per sample (16-bit)
        return int(len(audio_bytes) / (24_000 * 1 * 2) * 1000)
