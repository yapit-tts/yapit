"""OpenAI-compatible TTS adapter — calls any /v1/audio/speech endpoint."""

import asyncio
import io
import random

import av
import openai
from loguru import logger

from yapit.gateway.metrics import log_event
from yapit.workers.adapters.base import SynthAdapter

RETRYABLE_STATUS_CODES = {429, 500, 503, 504}
MAX_RETRIES = 6
BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 30.0

OGG_MAGIC = b"OggS"


class OpenAITTSAdapter(SynthAdapter):
    def __init__(self, base_url: str, api_key: str, model: str):
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._client: openai.AsyncOpenAI | None = None

    async def initialize(self) -> None:
        self._client = openai.AsyncOpenAI(base_url=self._base_url, api_key=self._api_key)

    async def synthesize(self, text: str, **kwargs) -> bytes:
        assert self._client is not None, "Adapter not initialized"
        voice = kwargs.get("voice", "alloy")
        audio_bytes = await self._call_with_retry(text, voice)
        if audio_bytes[:4] == OGG_MAGIC:
            return audio_bytes
        return await asyncio.get_running_loop().run_in_executor(None, _transcode_to_ogg_opus, audio_bytes)

    def calculate_duration_ms(self, audio_bytes: bytes) -> int:
        if not audio_bytes:
            return 0
        return _get_duration_ms(audio_bytes)

    async def _call_with_retry(self, text: str, voice: str) -> bytes:
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.audio.speech.create(
                    model=self._model,
                    voice=voice,  # type: ignore[arg-type]
                    input=text,
                    response_format="opus",
                )
                return response.read()

            except openai.APIStatusError as e:
                last_error = e
                if e.status_code not in RETRYABLE_STATUS_CODES:
                    raise

                if e.status_code == 429:
                    await log_event(
                        "api_rate_limit",
                        status_code=429,
                        retry_count=attempt,
                        data={"api_name": "openai_tts", "model": self._model},
                    )

                if attempt < MAX_RETRIES - 1:
                    delay = min(BASE_DELAY_SECONDS * (2**attempt), MAX_DELAY_SECONDS)
                    jitter = random.uniform(0, delay * 0.5)
                    wait_time = delay + jitter
                    logger.bind(model=self._model, voice=voice).warning(
                        f"OpenAI TTS error {e.status_code}, "
                        f"attempt {attempt + 1}/{MAX_RETRIES}, retrying in {wait_time:.1f}s"
                    )
                    await asyncio.sleep(wait_time)

            except (openai.APIConnectionError, openai.APITimeoutError) as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = min(BASE_DELAY_SECONDS * (2**attempt), MAX_DELAY_SECONDS)
                    jitter = random.uniform(0, delay * 0.5)
                    wait_time = delay + jitter
                    logger.bind(model=self._model, voice=voice).warning(
                        f"OpenAI TTS {type(e).__name__}: {e or '(no details)'}, "
                        f"attempt {attempt + 1}/{MAX_RETRIES}, retrying in {wait_time:.1f}s"
                    )
                    await asyncio.sleep(wait_time)

        assert last_error is not None
        raise last_error


def _get_duration_ms(audio_bytes: bytes) -> int:
    """Read duration from OGG Opus container, fall back to byte-size estimate."""
    try:
        container = av.open(io.BytesIO(audio_bytes), "r")
        try:
            if container.duration is not None:
                return int(container.duration / 1_000)  # av duration is in microseconds
        finally:
            container.close()
    except Exception as e:
        logger.warning(f"Could not read OGG duration, falling back to byte-size estimate: {e}")
    return int((len(audio_bytes) / 14_500) * 1000)


def _transcode_to_ogg_opus(audio_bytes: bytes) -> bytes:
    """Transcode any audio format (mp3, wav, opus, etc.) to OGG Opus."""
    inp = av.open(io.BytesIO(audio_bytes), "r")
    buf = io.BytesIO()
    out = av.open(buf, "w", format="ogg")
    stream = out.add_stream("libopus", rate=48_000)
    stream.bit_rate = 48_000

    for frame in inp.decode(audio=0):
        frame.pts = None
        for pkt in stream.encode(frame):
            out.mux(pkt)
    for pkt in stream.encode(None):
        out.mux(pkt)

    out.close()
    inp.close()
    return buf.getvalue()
