import asyncio
import shutil
from contextlib import asynccontextmanager

import httpx
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, text
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from yapit.gateway import create_app
from yapit.gateway.auth import authenticate
from yapit.gateway.cache import CacheConfig
from yapit.gateway.config import Settings
from yapit.gateway.db import close_db, create_session, get_engine, init_db
from yapit.gateway.deps import create_cache, create_image_storage
from yapit.gateway.markdown.transformer import DocumentTransformer
from yapit.gateway.rate_limit import limiter
from yapit.gateway.stack_auth.users import User

DEFAULT_TEST_USER = User(
    id="default-test-user",
    primary_email_verified=True,
    primary_email_auth_enabled=True,
    signed_up_at_millis=1234567890000,
    last_active_at_millis=1234567890000,
    is_anonymous=False,
)


def _make_delete_statements():
    """Deferred because SQLModel.metadata isn't populated at import time.

    DELETE FROM is faster than TRUNCATE in testcontainers (0.43s → ~0.01s)
    because TRUNCATE acquires AccessExclusiveLock on each table.
    """
    # Reverse of sorted_tables = children before parents (FK safe)
    return [text(f"DELETE FROM {t.name}") for t in reversed(SQLModel.metadata.sorted_tables)]


_delete_stmts = None


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as postgres:
        yield postgres


@pytest.fixture(scope="session")
def redis_container():
    with RedisContainer("redis:7-alpine") as redis:
        yield redis


@pytest.fixture(scope="session")
def _create_schema(postgres_container):
    """Create DB schema once for the entire test session."""
    engine = create_async_engine(postgres_container.get_connection_url())

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        await engine.dispose()

    asyncio.run(_setup())


@pytest.fixture(scope="session")
def _test_settings(postgres_container, redis_container):
    return Settings(
        database_url=postgres_container.get_connection_url(),
        redis_url=f"redis://{redis_container.get_container_host_ip()}:{redis_container.get_exposed_port(6379)}",
        audio_cache_config=CacheConfig(path="test_audio_cache"),
        document_cache_config=CacheConfig(path="test_document_cache"),
        stack_auth_api_host="",
        stack_auth_project_id="",
        stack_auth_server_key="",
        tts_processors_file="tests/empty_processors.json",
        ai_processor=None,
        metrics_database_url=None,
        log_dir="test_logs",
        db_drop_and_recreate=False,
        db_create_tables=False,
        db_seed=False,
    )


@pytest_asyncio.fixture(scope="session")
async def _shared_app(_create_schema, _test_settings) -> FastAPI:
    """Session-scoped app: containers, schema, and app state created once."""
    shutil.rmtree("test_audio_cache", ignore_errors=True)
    shutil.rmtree("test_document_cache", ignore_errors=True)

    settings = _test_settings
    limiter.enabled = False

    @asynccontextmanager
    async def _test_lifespan(app: FastAPI):
        """Minimal lifespan: app state only, no background tasks."""
        init_db(settings)
        app.state.redis_client = await aioredis.from_url(settings.redis_url, decode_responses=False)
        app.state.audio_cache = create_cache(settings.audio_cache_type, settings.audio_cache_config)
        app.state.document_cache = create_cache(settings.document_cache_type, settings.document_cache_config)
        app.state.extraction_cache = create_cache(settings.extraction_cache_type, settings.extraction_cache_config)
        app.state.image_storage = create_image_storage(settings)
        app.state.document_transformer = DocumentTransformer(
            max_block_chars=settings.max_block_chars,
            soft_limit_mult=settings.soft_limit_mult,
            min_chunk_size=settings.min_chunk_size,
        )
        app.state.ai_extractor_config = None
        app.state.ai_extractor = None
        yield
        for cache in [app.state.audio_cache, app.state.document_cache, app.state.extraction_cache]:
            await cache.close()
        await app.state.redis_client.aclose()
        await close_db()

    app = create_app(settings)
    app.router.lifespan_context = _test_lifespan
    app.dependency_overrides[authenticate] = lambda: DEFAULT_TEST_USER

    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables(_shared_app):
    """Clear all state between tests: DB rows, Redis, and SQLite caches."""
    global _delete_stmts
    if _delete_stmts is None:
        _delete_stmts = _make_delete_statements()

    engine = get_engine()
    async with engine.begin() as conn:
        for stmt in _delete_stmts:
            await conn.execute(stmt)
    await _shared_app.state.redis_client.flushdb()
    for cache in [_shared_app.state.audio_cache, _shared_app.state.document_cache, _shared_app.state.extraction_cache]:
        writer = await cache._get_writer()
        await writer.execute("DELETE FROM cache")
        await writer.commit()


@pytest.fixture
def app(_shared_app):
    """Per-test alias so tests can use `app` as fixture name."""
    return _shared_app


@pytest.fixture
def test_user():
    return User(
        id="test-user-123",
        primary_email_verified=True,
        primary_email_auth_enabled=True,
        signed_up_at_millis=1234567890,
        last_active_at_millis=1234567890,
        is_anonymous=False,
        primary_email="test@example.com",
    )


@pytest.fixture
def as_test_user(app, test_user):
    app.dependency_overrides[authenticate] = lambda: test_user
    yield test_user
    app.dependency_overrides[authenticate] = lambda: DEFAULT_TEST_USER


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def session():
    async with create_session() as session:
        yield session
