import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from yapit.gateway.api.v1 import routers as v1_routers
from yapit.gateway.cache_listener import run_cache_listener
from yapit.gateway.config import get_settings
from yapit.gateway.db import SessionLocal, close_db, prepare_database
from yapit.gateway.deps import get_audio_cache
from yapit.gateway.redis_client import close_redis, get_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    await prepare_database()

    listener_task = asyncio.create_task(run_cache_listener(redis=await get_redis(), cache=get_audio_cache()))

    yield

    listener_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await listener_task
    await close_db()
    await close_redis()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Yapit Gateway",
        version="0.1.0",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for r in v1_routers:
        app.include_router(r)
    return app


app = create_app()
