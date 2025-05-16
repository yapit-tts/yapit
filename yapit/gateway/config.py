from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from yapit.gateway.cache import CacheConfig, Caches
from yapit.gateway.text_splitter import TextSplitterConfig, TextSplitters


class Settings(BaseSettings):
    sqlalchemy_echo: bool = False
    db_auto_create: bool = False
    db_seed: bool = False

    database_url: str = "postgresql+asyncpg://yapit:yapit@postgres:5432/yapit"
    redis_url: str = "redis://redis:6379/0"
    cors_origins: list[str] = ["http://localhost:5173"]

    cache_type: Caches = Caches.SQLITE
    splitter_type: TextSplitters = TextSplitters.HIERARCHICAL

    splitter_config: TextSplitterConfig = TextSplitterConfig()
    cache_config: CacheConfig = CacheConfig(path=Path(__file__).parent / "cache")

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        extra="ignore",
        env_nested_delimiter="__",
    )

    stack_auth_api_host: str = ""
    stack_auth_project_id: str = ""
    stack_auth_server_key: str = ""


@lru_cache  # singleton factory
def get_settings() -> Settings:  # di-friendly wrapper
    return Settings()
