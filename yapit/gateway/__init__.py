import asyncio
import datetime as dt
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

import redis.asyncio as redis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from loguru import logger
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import func
from sqlmodel import col, delete, select

from yapit.contracts import (
    TTS_DLQ,
    TTS_JOB_INDEX,
    TTS_JOBS,
    TTS_RESULTS,
    YOLO_DLQ,
    YOLO_JOBS,
    YOLO_QUEUE,
    YOLO_RESULT,
    get_queue_name,
)
from yapit.gateway.api.v1 import routers as v1_routers
from yapit.gateway.auth import ANONYMOUS_ID_PREFIX
from yapit.gateway.billing_consumer import run_billing_consumer
from yapit.gateway.billing_sync import run_billing_sync_loop
from yapit.gateway.cache import Cache
from yapit.gateway.cache_persister import run_cache_persister
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.db import close_db, create_session, init_db, prepare_database
from yapit.gateway.deps import create_cache, create_image_storage
from yapit.gateway.document.batch_poller import BatchPoller
from yapit.gateway.document.defuddle_client import init_defuddle_client
from yapit.gateway.document.processors.gemini import GeminiExtractor, create_gemini_config
from yapit.gateway.document.types import BatchExtractor
from yapit.gateway.domain_models import Document, UsageLog, UserPreferences
from yapit.gateway.exceptions import APIError
from yapit.gateway.logging_config import (
    RequestContextMiddleware,
    configure_logging,
    unhandled_exception_handler,
)
from yapit.gateway.markdown.transformer import DocumentTransformer
from yapit.gateway.metrics import init_metrics_db, start_metrics_writer, stop_metrics_writer
from yapit.gateway.overflow_scanner import run_overflow_scanner
from yapit.gateway.rate_limit import limiter
from yapit.gateway.result_consumer import run_result_consumer
from yapit.gateway.storage import ImageStorage
from yapit.gateway.visibility_scanner import run_visibility_scanner
from yapit.workers.adapters.inworld import InworldAdapter
from yapit.workers.tts_loop import run_api_tts_dispatcher

# Scanner constants
TTS_VISIBILITY_TIMEOUT_S = 20
TTS_OVERFLOW_THRESHOLD_S = 15
YOLO_VISIBILITY_TIMEOUT_S = 10
YOLO_OVERFLOW_THRESHOLD_S = 10
VISIBILITY_SCAN_INTERVAL_S = 15
OVERFLOW_SCAN_INTERVAL_S = 2
MAX_RETRIES = 3
USAGE_LOG_RETENTION_DAYS = 31
GUEST_DOC_TTL_DAYS = 30
EXTRACTION_PROMPT_PATH = Path(__file__).parent / "document" / "prompts" / "extraction.txt"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.dependency_overrides[get_settings]()
    assert isinstance(settings, Settings)

    await init_metrics_db(settings.metrics_database_url)
    await start_metrics_writer()

    init_db(settings)
    await prepare_database(settings)

    app.state.redis_client = await redis.from_url(settings.redis_url, decode_responses=False)
    app.state.audio_cache = create_cache(settings.audio_cache_type, settings.audio_cache_config)
    app.state.document_cache = create_cache(settings.document_cache_type, settings.document_cache_config)
    app.state.extraction_cache = create_cache(settings.extraction_cache_type, settings.extraction_cache_config)
    app.state.image_storage = create_image_storage(settings)
    app.state.document_transformer = DocumentTransformer(
        max_block_chars=settings.max_block_chars,
        soft_limit_mult=settings.soft_limit_mult,
        min_chunk_size=settings.min_chunk_size,
    )

    init_defuddle_client(settings.defuddle_service_url)

    # Document extractors
    if settings.ai_processor == "gemini":
        app.state.ai_extractor_config = create_gemini_config()
        app.state.ai_extractor = GeminiExtractor(
            api_key=settings.google_api_key,
            redis=app.state.redis_client,
            image_storage=app.state.image_storage,
            prompt_path=EXTRACTION_PROMPT_PATH,
        )
        logger.info("AI extractor: gemini")
    elif settings.ai_processor == "openai":
        from yapit.gateway.document.processors.openai_compat import OpenAIExtractor, create_openai_config

        assert settings.ai_processor_base_url, "AI_PROCESSOR_BASE_URL required for openai processor"
        assert settings.ai_processor_api_key, "AI_PROCESSOR_API_KEY required for openai processor"
        assert settings.ai_processor_model, "AI_PROCESSOR_MODEL required for openai processor"
        app.state.ai_extractor_config = create_openai_config(settings.ai_processor_model)
        app.state.ai_extractor = OpenAIExtractor(
            base_url=settings.ai_processor_base_url,
            api_key=settings.ai_processor_api_key,
            model=settings.ai_processor_model,
            prompt_path=EXTRACTION_PROMPT_PATH,
            redis=app.state.redis_client,
            image_storage=app.state.image_storage,
        )
        logger.info(f"AI extractor: openai ({settings.ai_processor_model} @ {settings.ai_processor_base_url})")
    else:
        app.state.ai_extractor_config = None
        app.state.ai_extractor = None

    background_tasks: list[asyncio.Task] = []

    # TTS result consumer (hot path: Redis SET + notify, no SQLite, no Postgres)
    result_consumer_task = asyncio.create_task(run_result_consumer(app.state.redis_client))
    background_tasks.append(result_consumer_task)

    # Cache persister (drain-on-wake: Redis audio → batched SQLite writes)
    cache_persister_task = asyncio.create_task(run_cache_persister(app.state.redis_client, app.state.audio_cache))
    background_tasks.append(cache_persister_task)

    # TTS billing consumer (cold path: Postgres on own connection pool)
    billing_consumer_task = asyncio.create_task(run_billing_consumer(app.state.redis_client, settings.database_url))
    background_tasks.append(billing_consumer_task)

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
    if (
        settings.kokoro_runpod_serverless_endpoint
        and settings.runpod_api_key
        and settings.runpod_request_timeout_seconds
    ):
        tts_overflow_task = asyncio.create_task(
            run_overflow_scanner(
                app.state.redis_client,
                runpod_api_key=settings.runpod_api_key,
                runpod_request_timeout_seconds=settings.runpod_request_timeout_seconds,
                queue_name=get_queue_name("kokoro"),
                jobs_key=TTS_JOBS,
                job_index_key=TTS_JOB_INDEX,
                endpoint_id=settings.kokoro_runpod_serverless_endpoint,
                result_key_pattern=TTS_RESULTS,
                overflow_threshold_s=TTS_OVERFLOW_THRESHOLD_S,
                scan_interval_s=OVERFLOW_SCAN_INTERVAL_S,
                name="tts-overflow",
                max_retries=MAX_RETRIES,
                dlq_key=TTS_DLQ.format(model="kokoro"),
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
    if settings.yolo_runpod_serverless_endpoint and settings.runpod_api_key and settings.runpod_request_timeout_seconds:
        yolo_overflow_task = asyncio.create_task(
            run_overflow_scanner(
                app.state.redis_client,
                runpod_api_key=settings.runpod_api_key,
                runpod_request_timeout_seconds=settings.runpod_request_timeout_seconds,
                queue_name=YOLO_QUEUE,
                jobs_key=YOLO_JOBS,
                job_index_key=None,
                endpoint_id=settings.yolo_runpod_serverless_endpoint,
                result_key_pattern=YOLO_RESULT,
                overflow_threshold_s=YOLO_OVERFLOW_THRESHOLD_S,
                scan_interval_s=OVERFLOW_SCAN_INTERVAL_S,
                name="yolo-overflow",
                max_retries=MAX_RETRIES,
                dlq_key=YOLO_DLQ,
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

    background_tasks.append(asyncio.create_task(_usage_log_cleanup_task()))
    background_tasks.append(asyncio.create_task(_guest_cleanup_task(app.state.image_storage)))

    if settings.stripe_secret_key:
        background_tasks.append(
            asyncio.create_task(run_billing_sync_loop(settings.stripe_secret_key, app.state.redis_client))
        )

    # Batch extraction poller (only for extractors that support batch)
    batch_poller = None
    if isinstance(app.state.ai_extractor, BatchExtractor):
        config = app.state.ai_extractor_config
        assert config is not None and config.extraction_cache_prefix is not None
        batch_poller = BatchPoller(
            gemini_client=app.state.ai_extractor.client,
            redis=app.state.redis_client,
            extraction_cache=app.state.extraction_cache,
            transformer=app.state.document_transformer,
            extraction_cache_prefix=config.extraction_cache_prefix,
            output_token_multiplier=config.output_token_multiplier,
        )
        await batch_poller.start()

    yield

    if batch_poller:
        await batch_poller.stop()

    for task in background_tasks:
        task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)

    for cache in all_caches:
        await cache.close()

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


async def _usage_log_cleanup_task() -> None:
    """Delete UsageLog entries older than retention period."""
    await asyncio.sleep(3600)  # Wait 1h after startup before first run
    while True:
        try:
            cutoff = datetime.now(tz=dt.UTC) - timedelta(days=USAGE_LOG_RETENTION_DAYS)
            async with create_session() as db:
                result = await db.exec(delete(UsageLog).where(col(UsageLog.created) < cutoff))
                await db.commit()
                if result.rowcount:
                    logger.info(
                        f"UsageLog cleanup: deleted {result.rowcount} rows older than {USAGE_LOG_RETENTION_DAYS} days"
                    )
        except Exception as e:
            logger.exception(f"UsageLog cleanup failed: {e}")
        await asyncio.sleep(86400)


async def _guest_cleanup_task(image_storage: ImageStorage) -> None:
    """Delete inactive guest users and all their data.

    A guest user is inactive if none of their documents have been played or
    created within GUEST_DOC_TTL_DAYS.
    """
    from yapit.gateway.api.v1.documents import delete_documents_with_images

    await asyncio.sleep(120)
    while True:
        try:
            cutoff = datetime.now(tz=dt.UTC) - timedelta(days=GUEST_DOC_TTL_DAYS)
            async with create_session() as db:
                # Find guest users whose most recent activity is older than cutoff
                inactive_users = await db.exec(
                    select(Document.user_id)
                    .where(col(Document.user_id).startswith(ANONYMOUS_ID_PREFIX))
                    .group_by(Document.user_id)
                    .having(func.max(func.coalesce(Document.last_played_at, Document.created)) < cutoff)
                )
                user_ids = list(inactive_users.all())

                if user_ids:
                    docs_result = await db.exec(select(Document).where(col(Document.user_id).in_(user_ids)))
                    deleted = await delete_documents_with_images(docs_result.all(), db, image_storage)
                    await db.exec(delete(UserPreferences).where(col(UserPreferences.user_id).in_(user_ids)))
                    await db.commit()
                    logger.info(f"Guest cleanup: {len(user_ids)} users, {deleted} docs")

                # Sweep orphaned guest preferences (no documents at all)
                orphaned = await db.exec(
                    select(UserPreferences.user_id).where(
                        col(UserPreferences.user_id).startswith(ANONYMOUS_ID_PREFIX),
                        ~col(UserPreferences.user_id).in_(
                            select(Document.user_id)
                            .where(col(Document.user_id).startswith(ANONYMOUS_ID_PREFIX))
                            .distinct()
                        ),
                    )
                )
                orphan_ids = list(orphaned.all())
                if orphan_ids:
                    await db.exec(delete(UserPreferences).where(col(UserPreferences.user_id).in_(orphan_ids)))
                    await db.commit()
                    logger.info(f"Guest cleanup: {len(orphan_ids)} orphaned preferences purged")
        except Exception as e:
            logger.exception(f"Guest cleanup failed: {e}")
        await asyncio.sleep(86400)


def create_app(
    settings: Settings | None = None,
) -> FastAPI:
    if settings is None:
        settings = Settings()  # type: ignore

    configure_logging(Path(settings.log_dir))

    app = FastAPI(
        title="Yapit Gateway",
        version="0.1.0",
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
        client_ip = request.client.host if request.client else "unknown"
        logger.warning(f"Rate limit hit: {client_ip} on {request.url.path}")
        return JSONResponse(
            status_code=429, content={"detail": "Too many requests. Please wait a moment and try again."}
        )

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError):
        if exc.status_code >= 500:
            logger.exception(f"API error: {exc}")
        else:
            logger.warning(f"API error: {exc}")
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

    @app.get("/v1/extraction-prompt")
    async def extraction_prompt():
        return PlainTextResponse(EXTRACTION_PROMPT_PATH.read_text())

    return app
