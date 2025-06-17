import asyncio
import base64
import importlib
import os
from functools import partial

import runpod

from yapit.workers.adapters.base import SynthAdapter


def _get_adapter() -> SynthAdapter:
    """Dynamically import and instantiate the appropriate adapter based on MODEL_SLUG env var."""
    model_slug = os.getenv("MODEL_SLUG")
    if not model_slug:
        raise ValueError("MODEL_SLUG environment variable must be set")

    # Extract base model name from slug (e.g., "kokoro-gpu" -> "kokoro")
    model_type = model_slug.split("-")[0]

    adapter_map = {
        "kokoro": "yapit.workers.adapters.kokoro.KokoroAdapter",
    }

    if model_type not in adapter_map:
        raise ValueError(f"Unknown model type: {model_type} (from MODEL_SLUG={model_slug})")

    module_path, class_name = adapter_map[model_type].rsplit(".", 1)
    module = importlib.import_module(module_path)
    adapter_class = getattr(module, class_name)
    return adapter_class()


async def async_handler(job, adapter: SynthAdapter):
    """RunPod handler for any TTS model."""
    job_input = job["input"]

    text = job_input["text"]
    voice = job_input["voice"]
    speed = job_input["speed"]
    kwargs = job_input.get("kwargs", {})

    try:
        audio_bytes = await adapter.synthesize(text, voice=voice, speed=speed, **kwargs)
        duration_ms = adapter.calculate_duration_ms(audio_bytes)
        return {
            "audio_base64": base64.b64encode(audio_bytes).decode("utf-8"),
            "duration_ms": duration_ms,
            "sample_rate": adapter.sample_rate,
            "channels": adapter.channels,
            "sample_width": adapter.sample_width,
            "codec": adapter.native_codec,
        }
    except Exception as e:
        return {"error": str(e)}


def handler(job, adapter: SynthAdapter):
    """Synchronous wrapper for RunPod."""
    return asyncio.run(async_handler(job, adapter))


def main() -> None:
    adapter = _get_adapter()
    asyncio.run(adapter.initialize())
    print(f"Initialized {adapter.__class__.__name__} adapter")
    runpod.serverless.start({"handler": partial(handler, adapter=adapter)})


if __name__ == "__main__":
    main()
