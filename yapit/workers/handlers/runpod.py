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
