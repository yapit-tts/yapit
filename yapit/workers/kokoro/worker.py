import asyncio
import json
import logging
import os
from pathlib import Path

import numpy as np
import torch
from kokoro import KPipeline

from yapit.workers.synth_adapter import SynthAdapter

log = logging.getLogger("adapter.kokoro")


class KokoroAdapter(SynthAdapter):
    sample_rate = 24_000
    channels = 1
    sample_width = 2
    native_codec = "pcm"

    def __init__(self):
        self.device = os.getenv("DEVICE", "cpu")
        self.pipe: KPipeline | None = None
        self.voices: list[str] = []
        self.lock = asyncio.Lock()

    async def initialize(self) -> None:
        if self.pipe is not None:
            return
        if self.device == "cuda" and not torch.cuda.is_available():
            log.warning("CUDA requested but unavailable, falling back to CPU")
            self.device = "cpu"
        self.pipe = KPipeline(repo_id="hexgrad/Kokoro-82M", lang_code="a", device=self.device)

        voices_json = Path(__file__).with_name("voices.json")
        self.voices = [v["index"] for v in json.load(open(voices_json))]
        for v in self.voices:
            self.pipe.load_voice(v)  # TODO fix the  "unknown attribute of None" type error

    async def synthesize(self, text: str, *, voice: str, speed: float) -> bytes:
        await self.initialize()
        if voice not in self.voices:
            raise ValueError(f"Voice {voice} not found in available voices: {self.voices}")

        pcm_chunks = []
        async with self.lock:  # model not thread-safe
            for _, _, audio in self.pipe(text, voice=voice, speed=speed):  # TODO fix the None cant be called type error
                if audio is None:
                    continue
                pcm = (audio.numpy() * 32767).astype(np.int16).tobytes()  # scale [-1, 1] f32 tensor to int16 range
                pcm_chunks.append(pcm)

        return b"".join(pcm_chunks)
