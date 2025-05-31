from fastapi import FastAPI
from pytest import FixtureRequest
import pytest_asyncio

from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from yapit.gateway import create_app
from yapit.gateway.auth import ANON_USER, authenticate
from yapit.gateway.cache import CacheConfig, Caches
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.text_splitter import TextSplitterConfig, TextSplitters

postgres = PostgresContainer("postgres:16-alpine", driver="asyncpg")
redis = RedisContainer("redis:7-alpine")


@pytest_asyncio.fixture(scope="module", autouse=True)
async def app(request: FixtureRequest) -> FastAPI:
    postgres.start()
    request.addfinalizer(lambda: postgres.stop())

    redis.start()
    request.addfinalizer(lambda: redis.stop())

    app = create_app()
    app.dependency_overrides[authenticate] = lambda: ANON_USER

    postgres.driver

    app.dependency_overrides[get_settings] = lambda: Settings(
        sqlalchemy_echo=True,
        db_auto_create=True,
        db_seed=True,
        database_url=postgres.get_connection_url(),
        redis_url=redis.get_container_host_ip(),
        cors_origins=["*"],
        splitter_type=TextSplitters.HIERARCHICAL,
        splitter_config=TextSplitterConfig(max_chars=1000),
        audio_cache_type=Caches.NOOP,
        audio_cache_config=CacheConfig(),
        stack_auth_api_host="",
        stack_auth_project_id="",
        stack_auth_server_key="",
    )

    return app
