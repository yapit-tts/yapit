import pytest
import pytest_asyncio
from fastapi import FastAPI
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from yapit.gateway import create_app
from yapit.gateway.auth import ANON_USER, authenticate
from yapit.gateway.cache import CacheConfig, Caches
from yapit.gateway.config import Settings
from yapit.gateway.db import close_db
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


# Create test users
TEST_USER = User(
    id="test-user-123",
    primary_email_verified=True,
    primary_email_auth_enabled=True,
    signed_up_at_millis=1234567890,
    last_active_at_millis=1234567890,
    is_anonymous=False,
    primary_email="test@example.com",
)

ADMIN_USER = User(
    id="admin-user-123",
    primary_email_verified=True,
    primary_email_auth_enabled=True,
    signed_up_at_millis=1234567890,
    last_active_at_millis=1234567890,
    is_anonymous=False,
    primary_email="admin@example.com",
    server_metadata=UserServerMetadata(is_admin=True),
)


@pytest_asyncio.fixture
async def client(app):
    """Test client with auth overrides."""
    import httpx
    from httpx import AsyncClient

    async with AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def session(app):
    """Database session for tests."""
    from yapit.gateway.config import get_settings
    from yapit.gateway.db import create_session

    settings = app.dependency_overrides[get_settings]()
    async for session in create_session(settings):
        yield session
        break
