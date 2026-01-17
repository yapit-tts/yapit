"""RunPod serverless handler for TTS overflow.

This module runs ON RunPod as a serverless worker. The gateway's overflow_scanner
sends jobs here when the main queue backs up (jobs older than 30s).

Environment variables:
    ADAPTER_CLASS: Full path to the adapter class to use.
        Example: yapit.workers.adapters.kokoro.KokoroAdapter

Usage:
    Deploy to RunPod with CMD: python -m yapit.workers.handlers.runpod

The handler receives SynthesisParameters (text, kwargs) and returns:
    {audio_base64: str, duration_ms: int, audio_tokens?: str}
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
    """RunPod handler for any TTS model."""
    job_input = job["input"]
    try:
        audio = await adapter.synthesize(job_input["text"], **job_input.get("kwargs", {}))
        result = {
            "audio_base64": base64.b64encode(audio).decode("utf-8") if isinstance(audio, bytes) else audio,
            "duration_ms": adapter.calculate_duration_ms(
                audio if isinstance(audio, bytes) else base64.b64decode(audio)
            ),
        }
        # Include audio tokens if adapter supports context accumulation (e.g., HIGGS native)
        if hasattr(adapter, "get_audio_tokens"):
            audio_tokens = adapter.get_audio_tokens()
            if audio_tokens:
                result["audio_tokens"] = audio_tokens
        return result
    except Exception as e:
        return {"error": str(e)}


def main() -> None:
    adapter = _get_adapter()
    asyncio.run(adapter.initialize())
    print(f"Initialized {adapter.__class__.__name__} adapter")
    runpod.serverless.start({"handler": partial(handler, adapter=adapter)})


if __name__ == "__main__":
    main()
