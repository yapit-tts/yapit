import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from yapit.gateway import create_app
from yapit.gateway.auth import ANON_USER, authenticate
from yapit.gateway.cache import CacheConfig, Caches
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.db import close_db, create_session
from yapit.gateway.stack_auth.users import User, UserServerMetadata
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
        db_drop_and_recreate=True,
        db_seed=True,
        database_url=postgres_container.get_connection_url(),
        redis_url=f"redis://{redis_container.get_container_host_ip()}:{redis_container.get_exposed_port(6379)}",
        cors_origins=["*"],
        splitter_type=TextSplitters.HIERARCHICAL,
        splitter_config=TextSplitterConfig(max_chars=1000),
        audio_cache_type=Caches.SQLITE,
        audio_cache_config=CacheConfig(path="test_audio_cache"),
        stack_auth_api_host="",
        stack_auth_project_id="",
        stack_auth_server_key="",
        endpoints_file="",  # No endpoints configured for unit tests
        runpod_api_key=None,
        runpod_request_timeout_seconds=None,
    )

    app = create_app(settings)
    app.dependency_overrides[authenticate] = lambda: ANON_USER

    async with app.router.lifespan_context(app) as lifespan_state:
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
