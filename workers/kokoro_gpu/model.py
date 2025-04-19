import asyncio
import os
import torch
from kokoro import KPipeline
from typing import AsyncGenerator

# Set number of threads for OpenMP operations
torch.set_num_threads(int(os.getenv("OMP_THREADS", "4")))


class TtsPipeline:
    """Thread-safe TTS pipeline singleton with model warmup."""

    def __init__(self):
        self.lock = asyncio.Lock()
        self.pipe = None

    async def warm_up(self, device: str = "cuda"):
        """Initialize the model if not already loaded."""
        if self.pipe is None:
            try:
                if device == "cuda" and torch.cuda.is_available():
                    self.pipe = KPipeline(lang_code="a", device=device)
                else:
                    if device == "cuda":
                        print("CUDA requested but not available, falling back to CPU")
                    self.pipe = KPipeline(lang_code="a", device="cpu")
            except Exception as e:
                print(f"Error initializing model on {device}: {e}")
                print("Falling back to CPU")
                self.pipe = KPipeline(lang_code="a", device="cpu")

            # Preload default voice
            self.pipe.load_voice("af_heart")

    async def stream(
        self, text: str, voice: str, speed: float, codec: str = "pcm"
    ) -> AsyncGenerator[tuple[str, str, bytes], None, None]:
        """
        Stream audio from text using the specified voice and speed.

        Args:
            text: The text to synthesize
            voice: The voice to use
            speed: Speech speed factor
            codec: Output audio codec (pcm or opus)

        Yields:
            Tuples of (grapheme_slice, phoneme_slice, audio_bytes)
        """
        await self.warm_up()

        async with self.lock:
            if codec == "opus":
                from audio import pcm_to_opus

            for gs, ps, audio in self.pipe(text, voice=voice, speed=speed):
                if audio is None:
                    continue

                if codec == "opus":
                    audio_bytes = pcm_to_opus(audio.numpy())
                else:
                    # Convert to 16-bit PCM
                    audio_int16 = (audio.numpy() * 32767).astype("int16")
                    audio_bytes = audio_int16.tobytes()

                yield gs, ps, audio_bytes


tts_pipeline = TtsPipeline()
