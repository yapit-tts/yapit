import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import redis.asyncio as redis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, ORJSONResponse
from loguru import logger

from yapit.gateway.api.v1 import routers as v1_routers
from yapit.gateway.cache import Cache
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.db import close_db, prepare_database
from yapit.gateway.deps import create_cache
from yapit.gateway.exceptions import APIError
from yapit.gateway.metrics import init_metrics_db, start_metrics_writer, stop_metrics_writer
from yapit.gateway.overflow_scanner import run_overflow_scanner
from yapit.gateway.processors.document.gemini import GeminiProcessor
from yapit.gateway.processors.document.markitdown import MarkitdownProcessor
from yapit.gateway.processors.document.yolo_client import YoloProcessor
from yapit.gateway.result_consumer import run_result_consumer
from yapit.gateway.visibility_scanner import run_visibility_scanner
from yapit.workers.adapters.inworld import InworldAdapter
from yapit.workers.queue_worker import run_worker

logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
    colorize=True,
)


def _configure_file_logging(log_dir: Path) -> None:
    """Add persistent JSON log file with rotation (50MB x 20 files = 1GB max)."""
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_dir / "gateway.jsonl",
        format="{message}",
        level="INFO",
        serialize=True,
        rotation="50 MB",
        retention=20,
        compression="gz",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.dependency_overrides[get_settings]()
    assert isinstance(settings, Settings)

    await init_metrics_db(settings.metrics_database_url)
    await start_metrics_writer()

    await prepare_database(settings)

    app.state.redis_client = await redis.from_url(settings.redis_url, decode_responses=False)
    app.state.audio_cache = create_cache(settings.audio_cache_type, settings.audio_cache_config)
    app.state.document_cache = create_cache(settings.document_cache_type, settings.document_cache_config)
    app.state.extraction_cache = create_cache(settings.extraction_cache_type, settings.extraction_cache_config)

    # Document processors
    app.state.free_processor = MarkitdownProcessor(settings=settings)
    if settings.ai_processor == "gemini":
        app.state.ai_processor = GeminiProcessor(redis=app.state.redis_client, settings=settings)
        logger.info("AI processor: gemini")
    else:
        app.state.ai_processor = None

    # TTS background tasks
    background_tasks: list[asyncio.Task] = []

    result_consumer_task = asyncio.create_task(
        run_result_consumer(app.state.redis_client, app.state.audio_cache, settings)
    )
    background_tasks.append(result_consumer_task)

    visibility_scanner_task = asyncio.create_task(run_visibility_scanner(app.state.redis_client))
    background_tasks.append(visibility_scanner_task)

    overflow_scanner_task = asyncio.create_task(run_overflow_scanner(app.state.redis_client, settings))
    background_tasks.append(overflow_scanner_task)

    # Inworld workers run in gateway (API calls, no local model)
    if settings.inworld_api_key:
        for model_id, model_slug in [("inworld-tts-1", "inworld"), ("inworld-tts-1-max", "inworld-max")]:
            adapter = InworldAdapter(api_key=settings.inworld_api_key, model_id=model_id)
            task = asyncio.create_task(run_worker(settings.redis_url, model_slug, adapter, f"inworld-{model_slug}"))
            background_tasks.append(task)
        logger.info("Inworld workers started")

    # YOLO figure detection processor
    yolo_processor = YoloProcessor(redis=app.state.redis_client, settings=settings)
    app.state.yolo_processor = yolo_processor
    yolo_processor_task = asyncio.create_task(yolo_processor.run())
    background_tasks.append(yolo_processor_task)

    all_caches = [app.state.audio_cache, app.state.document_cache, app.state.extraction_cache]
    maintenance_task = asyncio.create_task(_cache_maintenance_task(all_caches))
    background_tasks.append(maintenance_task)

    yield

    for task in background_tasks:
        task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)

    await stop_metrics_writer()
    await close_db()
    await app.state.redis_client.aclose()


async def _cache_maintenance_task(caches: list[Cache]) -> None:
    """Background task to vacuum caches if bloated."""
    await asyncio.sleep(60)
    while True:
        for cache in caches:
            try:
                await cache.vacuum_if_needed(bloat_threshold=2.0)
            except Exception as e:
                logger.exception(f"Cache vacuum failed: {e}")
        await asyncio.sleep(86400)


def create_app(
    settings: Settings | None = None,
) -> FastAPI:
    if settings is None:
        settings = Settings()  # type: ignore

    _configure_file_logging(Path(settings.log_dir))

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

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError):
        logger.exception(f"API error: {exc}")
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    for r in v1_routers:
        app.include_router(r)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/version")
    async def version():
        try:
            with open("/app/version.txt") as f:
                commit = f.read().strip()
        except FileNotFoundError:
            commit = "unknown"
        return {"commit": commit}

    return app
