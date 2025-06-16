import asyncio
import base64
import importlib
import os
from functools import partial

import runpod

from yapit.workers.synth_adapter import SynthAdapter


def get_adapter() -> SynthAdapter:
    """Dynamically import and instantiate the appropriate adapter based on MODEL_TYPE env var."""
    model_type = os.getenv("MODEL_TYPE")
    if not model_type:
        raise ValueError("MODEL_TYPE environment variable must be set")

    adapter_map = {
        "kokoro": "yapit.workers.kokoro.worker.KokoroAdapter",
    }

    if model_type not in adapter_map:
        raise ValueError(f"Unknown model type: {model_type}")

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


async def init_adapter() -> SynthAdapter:
    adapter = get_adapter()
    await adapter.initialize()
    print(f"Initialized {adapter.__class__.__name__} adapter")
    return adapter


if __name__ == "__main__":
    adapter = asyncio.run(init_adapter())
    runpod.serverless.start({"handler": partial(handler, adapter=adapter)})
