import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from yapit.gateway.api.v1 import routers as v1_routers
from yapit.gateway.cache_listener import run_cache_listener
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.db import close_db, prepare_database
from yapit.gateway.deps import get_audio_cache
from yapit.gateway.redis_client import create_redis_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.dependency_overrides[get_settings]()
    assert isinstance(settings, Settings)

    await prepare_database(settings)

    # Create app-specific Redis client
    app.state.redis_client = await create_redis_client(settings)

    listener_task = asyncio.create_task(
        run_cache_listener(
            redis=app.state.redis_client,
            cache=get_audio_cache(settings),
        )
    )

    yield

    listener_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await listener_task

    await close_db()

    # Close app-specific Redis client
    if hasattr(app.state, "redis_client") and app.state.redis_client:
        await app.state.redis_client.aclose()
        app.state.redis_client = None


def create_app(
        settings: Settings = Settings(),  # type: ignore
) -> FastAPI:
    app = FastAPI(
        title="Yapit Gateway",
        version="0.1.0",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )

    app.dependency_overrides[get_settings] = lambda: settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for r in v1_routers:
        app.include_router(r)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
