from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from yapit.gateway.cache import CacheConfig, Caches
from yapit.gateway.text_splitter import TextSplitterConfig, TextSplitters


class Settings(BaseSettings):
    sqlalchemy_echo: bool
    db_auto_create: bool
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
        env_file=".env",
        extra="ignore",
        env_nested_delimiter="__",
    )


@lru_cache  # singleton factory
def get_settings() -> Settings:  # di-friendly wrapper
    return Settings()  # type: ignore
