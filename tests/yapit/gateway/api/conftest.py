import pytest
import pytest_asyncio
from fastapi import FastAPI
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from yapit.gateway import create_app
from yapit.gateway.auth import ANON_USER, authenticate
from yapit.gateway.cache import CacheConfig, Caches
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.db import close_db
from yapit.gateway.redis_client import create_redis_client
from yapit.gateway.text_splitter import TextSplitterConfig, TextSplitters


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as postgres:
        yield postgres


@pytest.fixture(scope="session")
def redis_container():
    with RedisContainer("redis:7-alpine") as redis:
        yield redis


@pytest_asyncio.fixture(scope="function")
async def app(postgres_container, redis_container) -> FastAPI:
    # Clean up any existing database state
    await close_db()

    settings = Settings(
        sqlalchemy_echo=True,
        db_auto_create=True,
        db_seed=True,
        database_url=postgres_container.get_connection_url(),
        redis_url=f"redis://{redis_container.get_container_host_ip()}:{redis_container.get_exposed_port(6379)}",
        cors_origins=["*"],
        splitter_type=TextSplitters.HIERARCHICAL,
        splitter_config=TextSplitterConfig(max_chars=1000),
        audio_cache_type=Caches.NOOP,
        audio_cache_config=CacheConfig(),
        stack_auth_api_host="",
        stack_auth_project_id="",
        stack_auth_server_key="",
    )

    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: ANON_USER

    async with app.router.lifespan_context(app) as lifespan_state:
        yield app

    await close_db()


@pytest_asyncio.fixture
async def redis_client(app: FastAPI):
    """Get a SEPARATE Redis client for tests to interact with Redis directly."""
    settings = app.dependency_overrides[get_settings]()
    test_redis = await create_redis_client(settings)
    try:
        yield test_redis
    finally:
        await test_redis.aclose()
