import os

from pydantic_settings import BaseSettings, SettingsConfigDict

from yapit.gateway.cache import CacheConfig, Caches


class Settings(BaseSettings):
    sqlalchemy_echo: bool
    db_drop_and_recreate: bool  # If True: drops all tables and recreates (dev mode)
    db_create_tables: bool  # If True: create tables if missing, no Alembic (selfhost mode)
    db_seed: bool

    database_url: str
    redis_url: str
    cors_origins: list[str]

    audio_cache_type: Caches
    audio_cache_config: CacheConfig

    stack_auth_api_host: str
    stack_auth_project_id: str
    stack_auth_server_key: str

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

    # Image storage: "local" or "r2"
    image_storage_type: str
    images_dir: str | None = None  # Required for local storage

    # R2 config (required if image_storage_type == "r2")
    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket_name: str | None = None
    r2_public_url: str | None = None

    markxiv_url: str | None = None

    # Worker replica counts (for queue semaphore sizing)
    kokoro_cpu_replicas: int
    yolo_cpu_replicas: int

    document_max_download_size: int = 100 * 1024 * 1024  # 100MB default

    max_block_chars: int
    soft_limit_mult: float
    min_chunk_size: int

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


def get_settings() -> Settings:
    """Dependency injection placeholder - always overridden in create_app()."""
    raise NotImplementedError("get_settings should be overridden via dependency_overrides")
