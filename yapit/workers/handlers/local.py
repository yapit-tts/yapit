import base64
import importlib
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from yapit.contracts import SynthesisParameters
from yapit.workers.adapters.base import SynthAdapter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("local_handler")


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

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await adapter.initialize()
        log.info(f"Initialized {adapter.__class__.__name__} adapter")
        yield

    app = FastAPI(title="Local TTS Worker", lifespan=lifespan)

    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "healthy"}

    @app.post("/synthesize", response_model=SynthesizeResponse)
    async def synthesize(request: SynthesisParameters):
        """Synthesize speech from text."""
        log.info(f"Synthesis request: {len(request.text)} chars, voice={request.kwargs.get('voice')}")
        start = time.time()
        try:
            audio = await adapter.synthesize(request.text, **request.kwargs)
            elapsed = time.time() - start
            duration_ms = adapter.calculate_duration_ms(audio if isinstance(audio, bytes) else base64.b64decode(audio))
            log.info(f"Synthesis complete: {elapsed:.2f}s, audio={duration_ms}ms")
            return SynthesizeResponse(
                audio_base64=base64.b64encode(audio).decode("utf-8") if isinstance(audio, bytes) else audio,
                duration_ms=duration_ms,
            )
        except Exception as e:
            elapsed = time.time() - start
            log.error(f"Synthesis failed after {elapsed:.2f}s: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return app
