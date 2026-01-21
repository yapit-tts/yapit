import os
import shutil

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from yapit.gateway import create_app
from yapit.gateway.auth import authenticate
from yapit.gateway.cache import CacheConfig
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.db import close_db, create_session
from yapit.gateway.stack_auth.users import User, UserServerMetadata

# Default test user for auth mocking
DEFAULT_TEST_USER = User(
    id="default-test-user",
    primary_email_verified=True,
    primary_email_auth_enabled=True,
    signed_up_at_millis=1234567890000,
    last_active_at_millis=1234567890000,
    is_anonymous=False,
)


class CIPostgres:
    """Wrapper for CI service container to match testcontainers interface."""

    def __init__(self, url: str):
        self._url = url

    def get_connection_url(self) -> str:
        return self._url


class CIRedis:
    """Wrapper for CI service container to match testcontainers interface."""

    def __init__(self, url: str):
        self._url = url

    def get_container_host_ip(self) -> str:
        return "localhost"

    def get_exposed_port(self, _: int) -> int:
        return 6379


@pytest.fixture(scope="session")
def postgres_container():
    # CI provides pre-started service containers via env vars
    if url := os.environ.get("TEST_POSTGRES_URL"):
        yield CIPostgres(url)
    else:
        with PostgresContainer("postgres:16-alpine", driver="asyncpg") as postgres:
            yield postgres


@pytest.fixture(scope="session")
def redis_container():
    if os.environ.get("TEST_REDIS_URL"):
        yield CIRedis(os.environ["TEST_REDIS_URL"])
    else:
        with RedisContainer("redis:7-alpine") as redis:
            yield redis


@pytest_asyncio.fixture(scope="function")
async def app(postgres_container, redis_container) -> FastAPI:
    await close_db()

    shutil.rmtree("test_audio_cache", ignore_errors=True)
    shutil.rmtree("test_document_cache", ignore_errors=True)

    settings = Settings(
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
    )

    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: DEFAULT_TEST_USER

    async with app.router.lifespan_context(app):
        yield app

    await close_db()


@pytest.fixture
def test_user():
    """Regular test user."""
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
def admin_user():
    """Admin test user."""
    return User(
        id="admin-user-123",
        primary_email_verified=True,
        primary_email_auth_enabled=True,
        signed_up_at_millis=1234567890,
        last_active_at_millis=1234567890,
        is_anonymous=False,
        primary_email="admin@example.com",
        server_metadata=UserServerMetadata(is_admin=True),
    )


@pytest.fixture
def as_test_user(app, test_user):
    """Set auth to regular test user."""
    app.dependency_overrides[authenticate] = lambda: test_user
    yield test_user
    app.dependency_overrides.pop(authenticate, None)


@pytest.fixture
def as_admin_user(app, admin_user):
    """Set auth to admin user."""
    app.dependency_overrides[authenticate] = lambda: admin_user
    yield admin_user
    app.dependency_overrides.pop(authenticate, None)


@pytest_asyncio.fixture
async def client(app):
    """Test client with auth overrides."""
    async with AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def session(app):
    """Database session for tests."""
    settings = app.dependency_overrides[get_settings]()
    async for session in create_session(settings):
        yield session
        break
