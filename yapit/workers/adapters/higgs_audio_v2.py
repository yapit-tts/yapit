import base64
import logging
import os
import pprint
from pathlib import Path

import requests
from typing_extensions import TypedDict

from yapit.workers.adapters import SynthAdapter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_NAME = "higgs-audio-v2-generation-3B-base"

VLLM_PORT = int(os.environ.get("VLLM_PORT", "8000"))
VLLM_HOST = "localhost"


class VoiceConfig(TypedDict, total=False):
    seed: int
    temperature: float
    top_p: float
    top_k: int
    scene_description: str
    system_prompt: str
    ref_audio: str | None  # b64
    ref_audio_transcript: str | None  # text
    ref_preset: str | None  # voice preset name, takes precedence over ref_audio and ref_audio_transcript


DEFAULT_VOICE_CONFIG = VoiceConfig(
    seed=42,
    temperature=0.3,
    top_p=0.95,
    top_k=50,
    scene_description="Audio is recorded from a quiet room.",
    system_prompt="Generate audio following instruction.",
)


class HiggsAudioV2Adapter(SynthAdapter):
    def __init__(self, voice_presets_dir: str | None = None) -> None:
        super().__init__()
        self._initialized = False
        self._voice_presets_dir: Path | None = Path(voice_presets_dir) if voice_presets_dir else None
        self._voice_presets: dict[str, tuple[str, str]] | None = None
        if self._voice_presets_dir and not self._voice_presets_dir.is_dir():
            logger.error(f"voice presets dir is not a directory: {self._voice_presets_dir}")
            raise FileNotFoundError

    async def initialize(self) -> None:
        if self._voice_presets_dir is not None:
            return
        self._voice_presets = (
            {
                voice_dir.name: (
                    base64.b64encode((voice_dir / "audio.wav").read_bytes()).decode("utf-8"),
                    (voice_dir / "transcript.txt").read_text(encoding="utf-8").strip(),
                )
                for voice_dir in self._voice_presets_dir.iterdir()
            }
            if self._voice_presets_dir
            else {}
        )
        logger.info(
            f"Loaded voice presets from {self._voice_presets_dir}: {pprint.pformat(self._voice_presets.keys())}"
        )

    async def synthesize(self, text: str, **kwargs: VoiceConfig) -> str:
        voice_config = DEFAULT_VOICE_CONFIG.copy()
        voice_config.update(kwargs)
        temperature = voice_config.get("temperature")
        top_p = voice_config.get("top_p")
        top_k = voice_config.get("top_k")
        scene_description = voice_config.get("scene_description")
        system_prompt = voice_config.get("system_prompt")

        scene_description = f"<|scene_desc_start|>\n{scene_description}\n<|scene_desc_end|>"
        system_prompt = f"{system_prompt}\n\n{scene_description}" if scene_description else system_prompt
        messages = [{"role": "system", "content": system_prompt}]

        ref_audio, ref_transcript = self._voice_presets.get(
            voice_config.get("ref_preset"),
            (voice_config.get("ref_audio"), voice_config.get("ref_audio_transcript")),
        )
        if ref_audio and ref_transcript:
            messages.append({"role": "user", "content": ref_transcript})
            messages.append(
                {
                    "role": "assistant",
                    "content": [{"type": "input_audio", "input_audio": {"data": ref_audio, "format": "wav"}}],
                }
            )

        messages.append({"role": "user", "content": text})

        payload = {
            "model": MODEL_NAME,
            "messages": messages,
            "modalities": ["text", "audio"],
            "audio": {"format": "wav"},
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "stop": ["<|eot_id|>", "<|end_of_text|>", "<|audio_eos|>"],
        }
        if voice_config.get("seed") is not None:
            payload["seed"] = voice_config["seed"]

        logger.debug(f"Sending payload to vLLM: {pprint.pformat(payload)}")
        response = requests.post(f"http://localhost:{VLLM_PORT}/v1/chat/completions", json=payload)

        if response.status_code != 200:
            logger.error(f"vLLM returned {response.status_code}: {response.text}")
            response.raise_for_status()

        result = response.json()
        if "choices" not in result or not result["choices"]:
            logger.error(f"Unexpected response structure: {pprint.pformat(result)}")
            raise ValueError("Invalid response from vLLM")

        # vLLM returns WAV format, but we need to return raw PCM
        # The WAV has a 44-byte header we need to skip
        audio_data_b64 = result["choices"][0]["message"]["audio"]["data"]
        wav_bytes = base64.b64decode(audio_data_b64)
        pcm_bytes = wav_bytes[44:]
        return base64.b64encode(pcm_bytes).decode("utf-8")

    def calculate_duration_ms(self, audio_bytes: bytes) -> int:
        # 24000 Hz, 1 channel, 2 bytes per sample (16-bit)
        return int(len(audio_bytes) / (24_000 * 1 * 2) * 1000)
