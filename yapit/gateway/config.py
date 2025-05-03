from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from yapit.gateway.cache import CacheConfig
from yapit.gateway.domain_models import User
from yapit.gateway.text_splitter import TextSplitterConfig

ANON_USER = User(id="anonymous_user", email="anon@example.com", tier="free")


class Settings(BaseSettings):
    sqlalchemy_echo: bool = False
    db_auto_create: bool = False
    db_seed: bool = False

    database_url: str = "postgresql+asyncpg://yapit:yapit@postgres:5432/yapit"
    redis_url: str = "redis://redis:6379/0"
    cors_origins: list[str] = ["http://localhost:5173"]

    cache_type: Literal["noop", "filesystem", "s3"] = "noop"
    splitter_type: Literal["dummy", "spacy"] = "dummy"

    splitter_config: TextSplitterConfig = TextSplitterConfig()
    cache_config: CacheConfig = CacheConfig()

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        extra="ignore",
        env_nested_delimiter="__",
    )


@lru_cache  # singleton factory
def get_settings() -> Settings:  # di-friendly wrapper
    return Settings()
