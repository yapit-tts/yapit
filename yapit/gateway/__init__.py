import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import redis.asyncio as redis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, ORJSONResponse
from loguru import logger
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from yapit.contracts import (
    TTS_JOB_INDEX,
    TTS_JOBS,
    TTS_RESULTS,
    YOLO_JOBS,
    YOLO_QUEUE,
    YOLO_RESULT,
    get_queue_name,
)
from yapit.gateway.api.v1 import routers as v1_routers
from yapit.gateway.cache import Cache
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.db import close_db, prepare_database
from yapit.gateway.deps import create_cache
from yapit.gateway.document.gemini import GeminiExtractor, create_gemini_config
from yapit.gateway.exceptions import APIError
from yapit.gateway.logging_config import (
    RequestContextMiddleware,
    configure_logging,
    unhandled_exception_handler,
)
from yapit.gateway.metrics import init_metrics_db, start_metrics_writer, stop_metrics_writer
from yapit.gateway.overflow_scanner import run_overflow_scanner
from yapit.gateway.result_consumer import run_result_consumer
from yapit.gateway.visibility_scanner import run_visibility_scanner
from yapit.workers.adapters.inworld import InworldAdapter
from yapit.workers.tts_loop import run_api_tts_dispatcher

# Scanner constants
TTS_VISIBILITY_TIMEOUT_S = 30
TTS_OVERFLOW_THRESHOLD_S = 30
YOLO_VISIBILITY_TIMEOUT_S = 10
YOLO_OVERFLOW_THRESHOLD_S = 10
VISIBILITY_SCAN_INTERVAL_S = 15
OVERFLOW_SCAN_INTERVAL_S = 5
MAX_RETRIES = 3


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

    # Document extractors
    if settings.ai_processor == "gemini":
        app.state.ai_extractor_config = create_gemini_config()
        app.state.ai_extractor = GeminiExtractor(settings=settings, redis=app.state.redis_client)
        logger.info("AI extractor: gemini")
    else:
        app.state.ai_extractor_config = None
        app.state.ai_extractor = None

    background_tasks: list[asyncio.Task] = []

    # TTS result consumer
    result_consumer_task = asyncio.create_task(
        run_result_consumer(app.state.redis_client, app.state.audio_cache, settings)
    )
    background_tasks.append(result_consumer_task)

    # TTS visibility scanner
    tts_visibility_task = asyncio.create_task(
        run_visibility_scanner(
            app.state.redis_client,
            processing_pattern="tts:processing:*",
            jobs_key=TTS_JOBS,
            visibility_timeout_s=TTS_VISIBILITY_TIMEOUT_S,
            max_retries=MAX_RETRIES,
            scan_interval_s=VISIBILITY_SCAN_INTERVAL_S,
            name="tts-visibility",
        )
    )
    background_tasks.append(tts_visibility_task)

    # TTS overflow scanner (for Kokoro)
    if settings.kokoro_runpod_serverless_endpoint:
        tts_overflow_task = asyncio.create_task(
            run_overflow_scanner(
                app.state.redis_client,
                settings,
                queue_name=get_queue_name("kokoro"),
                jobs_key=TTS_JOBS,
                job_index_key=TTS_JOB_INDEX,
                endpoint_id=settings.kokoro_runpod_serverless_endpoint,
                result_key_pattern=TTS_RESULTS,
                overflow_threshold_s=TTS_OVERFLOW_THRESHOLD_S,
                scan_interval_s=OVERFLOW_SCAN_INTERVAL_S,
                name="tts-overflow",
            )
        )
        background_tasks.append(tts_overflow_task)

    # YOLO visibility scanner
    yolo_visibility_task = asyncio.create_task(
        run_visibility_scanner(
            app.state.redis_client,
            processing_pattern="yolo:processing:*",
            jobs_key=YOLO_JOBS,
            visibility_timeout_s=YOLO_VISIBILITY_TIMEOUT_S,
            max_retries=MAX_RETRIES,
            scan_interval_s=VISIBILITY_SCAN_INTERVAL_S,
            name="yolo-visibility",
        )
    )
    background_tasks.append(yolo_visibility_task)

    # YOLO overflow scanner
    if settings.yolo_runpod_serverless_endpoint:
        yolo_overflow_task = asyncio.create_task(
            run_overflow_scanner(
                app.state.redis_client,
                settings,
                queue_name=YOLO_QUEUE,
                jobs_key=YOLO_JOBS,
                job_index_key=None,
                endpoint_id=settings.yolo_runpod_serverless_endpoint,
                result_key_pattern=YOLO_RESULT,
                overflow_threshold_s=YOLO_OVERFLOW_THRESHOLD_S,
                scan_interval_s=OVERFLOW_SCAN_INTERVAL_S,
                name="yolo-overflow",
            )
        )
        background_tasks.append(yolo_overflow_task)

    # Inworld dispatchers run in gateway (API calls, unlimited parallelism)
    if settings.inworld_api_key:
        for model_id, model_slug in [
            ("inworld-tts-1.5-mini", "inworld-1.5"),
            ("inworld-tts-1.5-max", "inworld-1.5-max"),
        ]:
            adapter = InworldAdapter(api_key=settings.inworld_api_key, model_id=model_id)
            task = asyncio.create_task(
                run_api_tts_dispatcher(
                    redis_url=settings.redis_url,
                    model=model_slug,
                    adapter=adapter,
                    worker_id=f"gateway-{model_slug}",
                )
            )
            background_tasks.append(task)
        logger.info("Inworld dispatchers started")

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

    configure_logging(Path(settings.log_dir))

    limiter = Limiter(key_func=get_remote_address, default_limits=["1000/minute"])

    app = FastAPI(
        title="Yapit Gateway",
        version="0.1.0",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )
    app.state.limiter = limiter

    app.dependency_overrides[get_settings] = lambda: settings

    app.add_middleware(
        CORSMiddleware,  # type: ignore[arg-type]  # Starlette typing limitation
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SlowAPIMiddleware)  # type: ignore[arg-type]
    app.add_middleware(RequestContextMiddleware)  # type: ignore[arg-type]

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError):
        logger.exception(f"API error: {exc}")
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    app.add_exception_handler(Exception, unhandled_exception_handler)

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
