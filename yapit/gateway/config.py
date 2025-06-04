import os

from pydantic_settings import BaseSettings, SettingsConfigDict

from yapit.gateway.cache import CacheConfig, Caches
from yapit.gateway.text_splitter import TextSplitterConfig, TextSplitters


class Settings(BaseSettings):
    sqlalchemy_echo: bool
    db_auto_create: bool  # If True: drops all tables and recreates (dev mode). TODO: rename to db_drop_and_recreate
    db_seed: bool

    database_url: str
    redis_url: str
    cors_origins: list[str]

    splitter_type: TextSplitters
    splitter_config: TextSplitterConfig

    audio_cache_type: Caches
    audio_cache_config: CacheConfig

    stack_auth_api_host: str
    stack_auth_project_id: str
    stack_auth_server_key: str

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=os.getenv("ENV_FILE", ".env"),
        extra="ignore",
        env_nested_delimiter="__",
    )


def get_settings() -> Settings:
    """This is only used for dependency references, see __init__.py:

    app.dependency_overrides[get_settings] = lambda: Settings()  # type: ignore
    """
    ...
