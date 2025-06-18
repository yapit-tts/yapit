import base64
import importlib
import logging
import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from yapit.workers.adapters.base import SynthAdapter

log = logging.getLogger("local_handler")


class SynthesizeRequest(BaseModel):
    text: str
    voice: str
    speed: float = 1.0


class SynthesizeResponse(BaseModel):
    audio_base64: str
    duration_ms: int


def _get_adapter(adapter_class_path: str) -> SynthAdapter:
    """Dynamically import and instantiate the specified adapter."""
    module_path, class_name = adapter_class_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    adapter_class = getattr(module, class_name)
    return adapter_class()


def create_app(adapter_class_path: str | None = None) -> FastAPI:
    """Create FastAPI app with synthesis endpoint."""
    if adapter_class_path is None:
        adapter_class_path = os.getenv("ADAPTER_CLASS")
    if not adapter_class_path:
        raise ValueError("ADAPTER_CLASS environment variable must be set")
    adapter = _get_adapter(adapter_class_path)

    app = FastAPI(title="Local TTS Worker")

    @app.on_event("startup")
    async def startup():
        """Initialize adapter on startup."""
        await adapter.initialize()
        log.info(f"Initialized {adapter.__class__.__name__} adapter")

    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "healthy"}

    @app.post("/synthesize", response_model=SynthesizeResponse)
    async def synthesize(request: SynthesizeRequest):
        """Synthesize speech from text."""
        try:
            audio_bytes = await adapter.synthesize(request.text, voice=request.voice, speed=request.speed)

            duration_ms = adapter.calculate_duration_ms(audio_bytes)

            return SynthesizeResponse(
                audio_base64=base64.b64encode(audio_bytes).decode("utf-8"), duration_ms=duration_ms
            )

        except Exception as e:
            log.error(f"Synthesis failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return app
