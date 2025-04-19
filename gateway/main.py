from __future__ import annotations

import orjson
import os
import uuid
from typing import Literal

import aioredis
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

MODEL_QUEUES = {
    "kokoro": os.getenv("MODEL_QUEUE_KOKORO", "tts:kokoro_gpu"),
}

# first‑choice voice per model; override in request with .voice
DEFAULT_VOICE: dict[str, str] = {
    "kokoro": "af_heart",
}


class TTSRequest(BaseModel):
    model: str = "kokoro"
    text: str
    voice: str | None = None
    speed: float = Field(1.0, ge=0.5, le=2.0)
    codec: Literal["pcm", "opus"] = "pcm"


app = FastAPI(title="Yapit Gateway")
redis: aioredis.Redis | None = None


@app.on_event("startup")
async def _startup() -> None:
    global redis
    redis = await aioredis.from_url(REDIS_URL, decode_responses=False)


@app.post("/v1/tts")
async def enqueue(req: TTSRequest) -> dict[str, str]:
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

    await redis.lpush(MODEL_QUEUES[req.model], orjson.dumps(payload))
    return {"job_id": job_id, "ws_url": f"/ws/{job_id}"}


@app.websocket("/ws/{job_id}")
async def stream(ws: WebSocket, job_id: str) -> None:
    """Proxy audio frames published by a worker over Redis → client WebSocket."""
    await ws.accept()
    channel = f"tts:{job_id}"
    pubsub = redis.pubsub()
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
