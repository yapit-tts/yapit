from functools import lru_cache
from typing import Literal

from pydantic import BaseModel
from pydantic import Field as PydanticField
from pydantic_settings import BaseSettings, SettingsConfigDict

from gateway.domain.models import User

ANON_USER = User(id="anonymous_user", email="anon@example.com", tier="free")  # TODO move this to the db seed func


class TextSplitterConfig(BaseModel):
    max_chars_per_block: int = PydanticField(default=1000, gt=0)


class CacheConfig(BaseModel):
    dir: str = "/cache"  # used only if cache_type is filesystem


class Settings(BaseSettings):
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
        extra="forbid",
        env_nested_delimiter="__",
    )


@lru_cache  # singleton factory
def get_settings() -> Settings:  # di-friendly wrapper
    return Settings()
