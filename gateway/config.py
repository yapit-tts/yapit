from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://yapit:yapit@postgres:5432/yapit"
    redis_url: str = "redis://redis:6379/0"
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="forbid")


@lru_cache  # singleton factory
def get_settings() -> Settings:  # di-friendly wrapper
    return Settings()
