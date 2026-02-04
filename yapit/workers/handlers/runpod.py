"""RunPod serverless handler for TTS overflow.

This module runs ON RunPod as a serverless worker. The gateway's overflow_scanner
sends jobs here when the TTS queue backs up (jobs older than 30s).

Deployment (Kokoro example):
    Image: ghcr.io/yapit-tts/kokoro-cpu:abc123 # do NOT use latest tag with runpod better to use their github integration
    CMD override: python -m yapit.workers.handlers.runpod
    Environment variables:
        ADAPTER_CLASS: yapit.workers.adapters.kokoro.KokoroAdapter

The overflow scanner sends the full SynthesisJob dict. The handler returns a
WorkerResult-compatible dict so the scanner can pass it straight through.
"""

import asyncio
import base64
import importlib
import os
from functools import partial

import runpod

from yapit.workers.adapters.base import SynthAdapter


def _get_adapter() -> SynthAdapter:
    """Dynamically import and instantiate the adapter based on ADAPTER_CLASS env var."""
    adapter_class_path = os.getenv("ADAPTER_CLASS")
    if not adapter_class_path:
        raise ValueError("ADAPTER_CLASS environment variable must be set")

    module_path, class_name = adapter_class_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    adapter_class = getattr(module, class_name)
    return adapter_class()


async def handler(job, adapter: SynthAdapter):
    """RunPod handler — receives SynthesisJob, returns WorkerResult-compatible dict."""
    job_input = job["input"]
    params = job_input["synthesis_parameters"]
    try:
        audio = await adapter.synthesize(params["text"], **params.get("kwargs", {}))
        audio_base64 = base64.b64encode(audio).decode("utf-8") if isinstance(audio, bytes) else audio
        return {
            "variant_hash": job_input["variant_hash"],
            "user_id": job_input["user_id"],
            "document_id": job_input["document_id"],
            "block_idx": job_input["block_idx"],
            "model_slug": job_input["model_slug"],
            "voice_slug": job_input["voice_slug"],
            "text_length": len(params["text"]),
            "usage_multiplier": job_input["usage_multiplier"],
            "audio_base64": audio_base64,
            "duration_ms": adapter.calculate_duration_ms(
                audio if isinstance(audio, bytes) else base64.b64decode(audio)
            ),
        }
    except Exception as e:
        return {"error": str(e)}


def main() -> None:
    adapter = _get_adapter()
    asyncio.run(adapter.initialize())
    print(f"Initialized {adapter.__class__.__name__} adapter")
    runpod.serverless.start({"handler": partial(handler, adapter=adapter)})


if __name__ == "__main__":
    main()
