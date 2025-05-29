from fastapi import FastAPI
import pytest_asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import SQLModel, StaticPool

from yapit.gateway import create_app
from yapit.gateway.auth import ANON_USER, authenticate
from yapit.gateway.cache import CacheConfig, Caches
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.deps import get_db_session
from yapit.gateway.text_splitter import TextSplitterConfig, TextSplitters


@pytest_asyncio.fixture
async def app() -> FastAPI:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    SessionLocal = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async with SessionLocal() as session:
        app = create_app()
        app.dependency_overrides[authenticate] = lambda: ANON_USER
        app.dependency_overrides[get_db_session] = lambda: session

        app.dependency_overrides[get_settings] = lambda: Settings(
            sqlalchemy_echo=True,
            db_auto_create=True,
            db_seed=True,
            database_url="sqlite://",
            redis_url="",
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
