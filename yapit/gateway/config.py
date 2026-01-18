import os

from pydantic_settings import BaseSettings, SettingsConfigDict

from yapit.gateway.cache import CacheConfig, Caches


class Settings(BaseSettings):
    sqlalchemy_echo: bool
    db_drop_and_recreate: bool  # If True: drops all tables and recreates (dev mode)
    db_seed: bool

    database_url: str
    redis_url: str
    cors_origins: list[str]

    audio_cache_type: Caches
    audio_cache_config: CacheConfig

    stack_auth_api_host: str
    stack_auth_project_id: str
    stack_auth_server_key: str

    tts_overflow_queue_threshold: int  # jobs per worker before routing to overflow
    kokoro_runpod_serverless_endpoint: str | None = None
    yolo_runpod_serverless_endpoint: str | None = None
    runpod_api_key: str | None = None
    runpod_request_timeout_seconds: int | None = None
    inworld_api_key: str | None = None

    document_cache_type: Caches
    document_cache_config: CacheConfig

    extraction_cache_type: Caches
    extraction_cache_config: CacheConfig

    ai_processor: str | None = None
    google_api_key: str | None = None
    images_dir: str

    # Worker replica counts (for queue semaphore sizing)
    kokoro_cpu_replicas: int
    yolo_cpu_replicas: int

    document_max_download_size: int = 100 * 1024 * 1024  # 100MB default

    max_block_chars: int
    soft_limit_mult: float
    min_chunk_size: int

    # TTS prefetch eviction window
    tts_buffer_behind: int  # Blocks to keep behind cursor for skip-back
    tts_buffer_ahead: int  # Prefetch window ahead of cursor

    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None

    # Stripe price IDs (from stripe_setup.py output)
    # Test IDs go in .env.dev, live IDs go in .env.prod
    stripe_price_basic_monthly: str | None = None
    stripe_price_basic_yearly: str | None = None
    stripe_price_plus_monthly: str | None = None
    stripe_price_plus_yearly: str | None = None
    stripe_price_max_monthly: str | None = None
    stripe_price_max_yearly: str | None = None

    billing_enabled: bool  # Self-hosting: set False to disable subscription/usage limits

    metrics_database_url: str | None
    log_dir: str

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=[os.getenv("ENV_FILE", ""), ".env"],
        extra="ignore",
        env_nested_delimiter="__",
    )


def get_settings() -> Settings:  # ty: ignore[invalid-return-type]
    """This is only used for dependency references, see __init__.py:

    app.dependency_overrides[get_settings] = lambda: Settings()  # type: ignore
    """
    ...
