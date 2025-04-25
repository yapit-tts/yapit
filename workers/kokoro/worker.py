import asyncio
import logging
import os

import numpy as np
import torch
from kokoro import KPipeline

from workers.base_worker import SynthAdapter, worker_loop

log = logging.getLogger("adapter.kokoro")


class KokoroAdapter(SynthAdapter):
    def __init__(self):
        self.device = os.getenv("DEVICE", "cpu")
        self.pipe: KPipeline | None = None
        self.lock = asyncio.Lock()

    async def warm_up(self) -> None:
        if self.pipe is not None:
            return
        if self.device == "cuda" and not torch.cuda.is_available():
            log.warning("CUDA requested but unavailable, falling back to CPU")
            self.device = "cpu"
        self.pipe = KPipeline(repo_id="hexgrad/Kokoro-82M", lang_code="a", device=self.device)
        self.pipe.load_voice("af_heart")

    async def stream(self, text: str, *, voice: str, speed: float, codec: str):
        await self.warm_up()
        assert self.pipe is not None
        async with self.lock:  # model not thread-safe
            for _, _, audio in self.pipe(text, voice=voice, speed=speed):
                if audio is None:
                    continue
                pcm = (audio.numpy() * 32767).astype(np.int16).tobytes()
                yield pcm


if __name__ == "__main__":
    asyncio.run(worker_loop(KokoroAdapter()))
