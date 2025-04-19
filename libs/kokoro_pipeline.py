from __future__ import annotations

import asyncio
import os
import torch
from typing import AsyncGenerator

from kokoro import KPipeline

# from libs.audio import pcm_to_opus

torch.set_num_threads(int(os.getenv("OMP_THREADS", "4")))


class TtsPipeline:
    """Thread‑safe Kokoro pipeline singleton."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.pipe: KPipeline | None = None

    async def warm_up(self, device: str = "cpu") -> None:
        if self.pipe is not None:  # already loaded
            return
        if device == "cuda" and not torch.cuda.is_available():
            print("CUDA requested but unavailable, falling back to CPU")
            device = "cpu"

        self.pipe = KPipeline(lang_code="a", device=device)
        self.pipe.load_voice("af_heart")

    async def stream(
        self, text: str, voice: str, speed: float, codec: str = "pcm"
    ) -> AsyncGenerator[tuple[str, str, bytes], None]:
        await self.warm_up()
        async with self.lock:
            for gs, ps, audio in self.pipe(text, voice=voice, speed=speed):
                if audio is None:
                    continue
                if codec == "opus":
                    raise NotImplementedError
                    # audio_bytes = pcm_to_opus(audio.numpy(), sr=24_000)  # 24kHz fixed sr for kokoro
                else:  # int16 PCM
                    audio_int16 = (audio.numpy() * 32767).astype("int16")
                    audio_bytes = audio_int16.tobytes()
                yield gs, ps, audio_bytes


tts_pipeline = TtsPipeline()
