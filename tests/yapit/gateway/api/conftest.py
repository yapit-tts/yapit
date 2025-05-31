from fastapi import FastAPI
from pytest import FixtureRequest
import pytest
import pytest_asyncio

from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from yapit.gateway import create_app
from yapit.gateway.auth import ANON_USER, authenticate
from yapit.gateway.cache import CacheConfig, Caches
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.text_splitter import TextSplitterConfig, TextSplitters
from yapit.gateway.db import prepare_database, close_db


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
    
    app = create_app()
    app.dependency_overrides[authenticate] = lambda: ANON_USER

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
    
    app.dependency_overrides[get_settings] = lambda: settings
    
    # Drop and recreate all tables to ensure clean state
    from yapit.gateway.db import _get_engine
    from sqlmodel import SQLModel
    
    engine = _get_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    
    # Seed the database
    from yapit.gateway.db import _seed_db
    await _seed_db(settings)

    yield app
    
    # Clean up
    await close_db()
