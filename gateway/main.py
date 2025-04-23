from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from typing import Literal

import aioredis
import orjson
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ─── config ─────────────────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
MODEL_QUEUES = {"kokoro": os.getenv("MODEL_QUEUE_KOKORO", "tts:kokoro_gpu"), "kokoro-cpu": "tts:kokoro_cpu"}
DEFAULT_VOICE = {
    "kokoro": "af_heart",
    "kokoro-cpu": "af_heart",
}


# ─── pydantic shapes ────────────────────────────────────────────────────────────
class TTSRequest(BaseModel):
    model: str = "kokoro"
    text: str
    voice: str | None = None
    speed: float = Field(1.0, ge=0.5, le=2.0)
    codec: Literal["pcm", "opus"] = "pcm"


# ─── lifespan ───────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    redis = await aioredis.from_url(REDIS_URL, decode_responses=False)
    app.state.redis = redis  # shared handle
    yield
    await redis.close()


app = FastAPI(title="Yapit Gateway", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # temporary for local testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── helpers ────────────────────────────────────────────────────────────────────
def redis_handle(request_or_ws) -> aioredis.Redis:
    return request_or_ws.app.state.redis


# ─── routes ─────────────────────────────────────────────────────────────────────
@app.post("/v1/tts")
async def enqueue(req: TTSRequest, request: Request) -> dict[str, str]:
    """Push a synthesis job to the correct model queue and return the WS URL."""
    if req.model not in MODEL_QUEUES:
        raise HTTPException(400, f"unknown model '{req.model}'")

    job_id = uuid.uuid4().hex
    channel = f"tts:{job_id}"

    payload = {
        "job_id": job_id,
        "channel": channel,
        "model": req.model,
        "voice": req.voice or DEFAULT_VOICE[req.model],
        "text": req.text,
        "speed": req.speed,
        "codec": req.codec,
    }
    await redis_handle(request).lpush(MODEL_QUEUES[req.model], orjson.dumps(payload))
    return {"job_id": job_id, "ws_url": f"/ws/{job_id}"}


@app.websocket("/ws/{job_id}")
async def stream(ws: WebSocket, job_id: str) -> None:
    """Proxy audio frames published by a worker over Redis → client WebSocket."""
    await ws.accept()
    channel = f"tts:{job_id}"
    pubsub = redis_handle(ws).pubsub()
    await pubsub.subscribe(channel)

    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30)
            if msg and msg["type"] == "message":
                await ws.send_bytes(msg["data"])
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}
