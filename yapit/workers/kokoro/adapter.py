import asyncio
import io
import json
import os
from pathlib import Path
from typing import Unpack

import av
import numpy as np
import torch
from kokoro import KModel, KPipeline
from typing_extensions import TypedDict

from yapit.synth import SynthAdapter

DEVICE: str = os.getenv("DEVICE", "")

REPO_ID = "hexgrad/Kokoro-82M"
KOKORO_SAMPLE_RATE = 24_000
OPUS_BITRATE = 48_000

# Kokoro's non-English chunker only splits on ASCII sentence enders and silently truncates
# chunks over 510 phonemes — a single 250-char CJK block far exceeds that. Splitting on CJK
# enders too keeps chunks under the cap. (Applies to every language: an English ellipsis
# also becomes a chunk boundary, i.e. a slight pause.)
SPLIT_PATTERN = r"\n+|(?<=[。！？…])"


class VoiceConfig(TypedDict):
    voice: str
    speed: float


class KokoroAdapter(SynthAdapter[VoiceConfig]):
    def __init__(self):
        if not DEVICE:
            raise ValueError("DEVICE environment variable must be set to 'cpu' or 'cuda'")
        if DEVICE == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but unavailable, please check your setup.")
        self._model: KModel | None = None
        self._pipes: dict[str, KPipeline] = {}
        self._voices_by_lang: dict[str, list[str]] = {}
        self._lock = asyncio.Lock()
        self._last_duration_ms: int = 0
        self._last_word_timestamps: list[dict] | None = None

    async def initialize(self) -> None:
        if self._model is not None:
            return
        self._model = KModel(repo_id=REPO_ID).to(DEVICE).eval()
        for v in json.loads((Path(__file__).parent / "voices.json").read_text()):
            self._voices_by_lang.setdefault(_lang_code(v["index"]), []).append(v["index"])
        self._pipeline("a")  # pre-warm the common case; other languages init on first use

    def _pipeline(self, lang_code: str) -> KPipeline:
        """Pipelines own the language's G2P frontend, so there is one per language (the voice
        slug's first letter), created lazily and all sharing the single model.
        """
        assert self._model is not None, "Adapter not initialized. Call initialize() first."
        if lang_code not in self._pipes:
            pipe = KPipeline(repo_id=REPO_ID, lang_code=lang_code, model=self._model)
            for voice in self._voices_by_lang[lang_code]:
                pipe.load_voice(voice)
            self._pipes[lang_code] = pipe
        return self._pipes[lang_code]

    async def synthesize(self, text: str, **kwargs: Unpack[VoiceConfig]) -> bytes:
        async with self._lock:  # model not thread-safe (usage as local worker with fastapi)
            pipe = self._pipeline(_lang_code(kwargs["voice"]))
            all_pcm: list[bytes] = []
            all_timestamps: list[dict] = []
            cumulative_s = 0.0

            for result in pipe(text, voice=kwargs["voice"], speed=kwargs["speed"], split_pattern=SPLIT_PATTERN):
                if result.audio is None:
                    continue
                pcm = (result.audio.numpy() * 32767).astype(np.int16).tobytes()
                all_pcm.append(pcm)

                if result.tokens:
                    for tok in result.tokens:
                        if tok.start_ts is not None and tok.end_ts is not None:
                            all_timestamps.append(
                                {
                                    "t": tok.text,
                                    "s": round(tok.start_ts + cumulative_s, 4),
                                    "e": round(tok.end_ts + cumulative_s, 4),
                                }
                            )

                cumulative_s += len(pcm) / (KOKORO_SAMPLE_RATE * 2)

            pcm = b"".join(all_pcm)

        # Calculate exact duration from PCM before lossy encoding
        self._last_duration_ms = int(len(pcm) / (KOKORO_SAMPLE_RATE * 2) * 1000)
        self._last_word_timestamps = all_timestamps if all_timestamps else None

        return _pcm_to_ogg_opus(pcm)

    def calculate_duration_ms(self, audio_bytes: bytes) -> int:
        return self._last_duration_ms

    def get_word_timestamps(self) -> list[dict] | None:
        return self._last_word_timestamps


def _lang_code(voice_slug: str) -> str:
    """Kokoro voice slugs start with their language code: ef_dora -> 'e' (Spanish)."""
    return voice_slug[0]


def _pcm_to_ogg_opus(pcm_bytes: bytes) -> bytes:
    """Encode raw 24kHz mono int16 PCM to OGG_OPUS."""
    if not pcm_bytes:
        return b""
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
