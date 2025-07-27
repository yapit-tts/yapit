import base64
import logging
import os
import pprint
import subprocess
import time
from pathlib import Path
from typing import NotRequired

import requests
from typing_extensions import TypedDict

from yapit.workers.adapters import SynthAdapter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_NAME = "higgs-audio-v2-generation-3B-base"

VLLM_PORT = int(os.environ.get("VLLM_PORT", "8000"))
VLLM_HOST = "localhost"


class VoiceConfig(TypedDict):
    seed: int
    temperature: float
    top_p: float
    top_k: int
    scene_description: NotRequired[str]
    system_prompt: NotRequired[str]
    ref_audio: NotRequired[str | None]  # b64
    ref_audio_transcript: NotRequired[str | None]  # text
    ref_preset: NotRequired[str | None]  # voice preset name, takes precedence over ref_audio and ref_audio_transcript


DEFAULT_VOICE_CONFIG = VoiceConfig(
    seed=42,
    temperature=0.3,
    top_p=0.95,
    top_k=50,
    scene_description="Audio is recorded from a quiet room.",
    system_prompt="Generate audio following instruction.",
    ref_audio=None,
    ref_audio_transcript=None,
)


class HiggsAudioV2Adapter(SynthAdapter):
    def __init__(self, voice_presets_dir: str | None = None) -> None:
        super().__init__()
        self._initialized = False
        self._voice_presets_dir: Path | None = Path(voice_presets_dir) if voice_presets_dir else None
        self._voice_presets: dict[str, tuple[str, str]] = {}
        if self._voice_presets_dir and not self._voice_presets_dir.is_dir():
            logger.error(f"voice presets dir is not a directory: {self._voice_presets_dir}")
            raise FileNotFoundError

    async def initialize(self) -> None:
        if self._initialized:
            return
        logger.info("Starting vLLM server...")

        # Use the same cache directories as set in Dockerfile
        download_dir = os.environ.get("VLLM_DOWNLOAD_DIR", "/root/.cache/vllm")

        cmd = (
            f"python3 -m vllm.entrypoints.bosonai.api_server "
            f"--served-model-name {MODEL_NAME} "
            f"--model bosonai/{MODEL_NAME} "
            f"--audio-tokenizer-type bosonai/higgs-audio-v2-tokenizer "
            f"--limit-mm-per-prompt audio=50 "
            f"--max-model-len 8192 "
            f"--port {VLLM_PORT} "
            f"--download-dir {download_dir} "
            f"--disable-mm-preprocessor-cache"
        ).split()
        subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(120):
            try:
                response = requests.get(f"http://localhost:{VLLM_PORT}/v1/models", timeout=1)
                if response.status_code == 200:
                    logger.info("vLLM server ready")
                    break
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("Failed to start vLLM server")
        self._voice_presets = {
            voice_dir.name: (
                base64.b64encode((voice_dir / "audio.wav").read_bytes()).decode("utf-8"),
                (voice_dir / "transcript.txt").read_text(encoding="utf-8").strip(),
            )
            for voice_dir in self._voice_presets_dir.iterdir()
        }
        logger.info(
            f"Loaded voice presets from {self._voice_presets_dir}: {pprint.pformat(self._voice_presets.keys())}"
        )
        self._initialized = True

    async def synthesize(self, text: str, **kwargs: VoiceConfig) -> str:
        voice_config = DEFAULT_VOICE_CONFIG.copy()
        voice_config.update(kwargs)
        temperature = voice_config["temperature"]
        top_p = voice_config["top_p"]
        top_k = voice_config["top_k"]
        scene_description = voice_config["scene_description"]
        system_prompt = voice_config["system_prompt"]

        scene_description = f"<|scene_desc_start|>\n{scene_description}\n<|scene_desc_end|>"
        system_prompt = f"{system_prompt}\n\n{scene_description}" if scene_description else system_prompt
        messages = [{"role": "system", "content": system_prompt}]

        ref_audio, ref_transcript = self._voice_presets.get(
            voice_config.get("ref_preset"), (voice_config["ref_audio"], voice_config["ref_audio_transcript"])
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
            "audio": {"format": "pcm"},
            "temperature": temperature,
            "top_p": top_p,
            "extra_body": {"top_k": top_k},
            "stop": ["<|eot_id|>", "<|end_of_text|>", "<|audio_eos|>"],
        }

        response = requests.post(f"http://localhost:{VLLM_PORT}/v1/chat/completions", json=payload)
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["audio"]["data"]

    def calculate_duration_ms(self, audio_bytes: bytes) -> int:
        # 24000 Hz, 1 channel, 2 bytes per sample (16-bit)
        return int(len(audio_bytes) / (24_000 * 1 * 2) * 1000)
