from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from yapit.gateway.api.v1 import routers as v1_routers
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.db import close_db, prepare_database
from yapit.gateway.deps import get_audio_cache
from yapit.gateway.processors.tts.manager import TTSProcessorManager
from yapit.gateway.redis_client import create_redis_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.dependency_overrides[get_settings]()
    assert isinstance(settings, Settings)

    await prepare_database(settings)

    app.state.redis_client = await create_redis_client(settings)

    tts_processor_manager = TTSProcessorManager(
        redis=app.state.redis_client,
        cache=get_audio_cache(settings),
        settings=settings,
    )

    await tts_processor_manager.start(settings.tts_processors_file)

    yield

    # Stop processor manager
    await tts_processor_manager.stop()

    await close_db()
    await app.state.redis_client.aclose()


def create_app(
    settings: Settings | None = None,
) -> FastAPI:
    if settings is None:
        settings = Settings()  # type: ignore

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
