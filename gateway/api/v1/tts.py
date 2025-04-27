import hashlib
import uuid

import orjson
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy import Select
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession
from typing_extensions import Literal, cast

from gateway.db import get_db
from gateway.domain.models import (
    Model as TtsModel,
)
from gateway.domain.models import (
    Voice,
)
from gateway.redis_client import get_redis

router = APIRouter(prefix="/v1", tags=["synthesis"])


class TTSIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=20_000)
    voice: str | None = None  # first voice wins if none requested
    speed: float = Field(1.0, ge=0.25, le=3.0)
    codec: Literal["pcm", "opus"] = "pcm"

    model_config = ConfigDict(extra="forbid")


class TTSOut(BaseModel):
    job_id: str
    ws_url: str
    est_sec: float


@router.post("/models/{model_id}/tts", response_model=TTSOut, status_code=201)
async def enqueue_tts(
    model_id: str,
    body: TTSIn,
    db: SQLModelAsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> TTSOut:
    pass
    # """Queue a synthesis job and return the WebSocket URL."""
    # # validate model
    # model_obj = await db.get(TtsModel, model_id)
    # if model_obj is None:
    #     raise HTTPException(status_code=404, detail=f"model '{model_id}' not found")
    #
    # # validate / choose voice
    # if body.voice:
    #     stmt = select(Voice).where(Voice.id == body.voice, Voice.model_id == model_id)
    #     stmt = cast(Select[Voice], stmt)
    #     voice_obj = (await db.exec(stmt)).first()
    #     if voice_obj is None:
    #         raise HTTPException(
    #             status_code=404,
    #             detail=f"voice '{body.voice}' not found for model '{model_id}'",
    #         )
    # else:
    #     if not model_obj.voices:
    #         raise HTTPException(status_code=500, detail=f"model '{model_id}' has no voices configured")
    #     voice_obj = model_obj.voices[0]
    #
    # # persist Job row
    # job_id = uuid.uuid4().hex
    # channel = f"tts:{job_id}"
    # text_sha256 = hashlib.sha256(body.text.encode()).hexdigest()
    # est_sec = len(body.text) / 15.0 / body.speed  # heuristic, 15 chars ≈ 1 s # XXX measure & evaluate
    # job = Job(
    #     id=job_id,
    #     user_id=None,
    #     model_id=model_id,
    #     voice_id=voice_obj.id,
    #     text_sha256=text_sha256,
    #     speed=body.speed,
    #     codec=body.codec,
    #     est_sec=est_sec,
    #     state=JobState.queued,
    # )
    # db.add(job)
    # await db.commit()
    #
    # # enqueue work on Redis
    # payload = {
    #     "job_id": job_id,
    #     "channel": channel,
    #     "model": model_id,
    #     "voice": voice_obj.id,
    #     "text": body.text,
    #     "speed": body.speed,
    #     "codec": body.codec,
    # }
    # await redis.lpush(f"tts:{model_id}", orjson.dumps(payload))
    #
    # return TTSOut(job_id=job_id, ws_url=f"/v1/ws/{job_id}", est_sec=est_sec)
    #


@router.websocket("/ws/{job_id}")
async def stream_audio(
    job_id: str,
    ws: WebSocket,
    redis: Redis = Depends(get_redis),
) -> None:
    """Proxy audio frames published by a worker Redis → WebSocket client."""
    await ws.accept()
    channel = f"tts:{job_id}"
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)

    try:
        while True:
            msg = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=30,  # sec – keeps the loop responsive
            )
            if msg and msg["type"] == "message":
                await ws.send_bytes(msg["data"])
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
