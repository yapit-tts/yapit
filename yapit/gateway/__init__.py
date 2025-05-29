import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from yapit.gateway.api.v1 import routers as v1_routers
from yapit.gateway.cache_listener import run_cache_listener
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.deps import get_audio_cache
from yapit.gateway.redis_client import close_redis, get_redis
from yapit.gateway.db import close_db, prepare_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.dependency_overrides[get_settings]()
    assert isinstance(settings, Settings)

    await prepare_database(settings)

    listener_task = asyncio.create_task(
        run_cache_listener(
            redis=await get_redis(settings),
            cache=get_audio_cache(settings),
        )
    )

    yield

    listener_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await listener_task
    await close_db()
    await close_redis()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Yapit Gateway",
        version="0.1.0",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )
    app.dependency_overrides[get_settings] = lambda: Settings()  # type: ignore

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for r in v1_routers:
        app.include_router(r)
    return app


app = create_app()
