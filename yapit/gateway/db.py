from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncIterator

from alembic import command, config
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.config import Settings
from yapit.gateway.exceptions import ResourceNotFoundError

ALEMBIC_INI = Path(__file__).parent / "alembic.ini"

_engine: AsyncEngine | None = None


def _get_engine(settings: Settings) -> AsyncEngine:
    global _engine
    if _engine is not None:
        return _engine
    _engine = create_async_engine(
        settings.database_url,
        echo=settings.sqlalchemy_echo,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
    return _engine


async def create_session(settings: Settings) -> AsyncIterator[AsyncSession]:
    engine = _get_engine(settings)

    SessionLocal = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with SessionLocal() as session:
        yield session


async def prepare_database(settings: Settings) -> None:
    """Bring the schema to the requested state.

    - DEV (DB_DROP_AND_RECREATE=1):   drop all tables and recreate from scratch
    - SELFHOST (DB_CREATE_TABLES=1):  create tables if missing, no Alembic
    - PROD (default):                 run Alembic `upgrade head`
    """
    engine = _get_engine(settings)
    if settings.db_drop_and_recreate:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
            await conn.run_sync(SQLModel.metadata.create_all)
    elif settings.db_create_tables:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
    else:
        alembic_cfg = config.Config(str(ALEMBIC_INI))
        # Set absolute path for migrations (relative path in ini doesn't work from /app)
        alembic_cfg.set_main_option("script_location", str(ALEMBIC_INI.parent / "migrations"))
        # Run in thread to avoid blocking event loop
        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
    if settings.db_seed:
        await _seed_db(settings)


async def close_db() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def _seed_db(settings: Settings) -> None:
    """Seed database with initial data (models, voices, plans, etc.)."""
    from yapit.gateway.seed import seed_database

    async for db in create_session(settings):
        await seed_database(db, settings)
        break  # only iterate once


async def get_or_404[T: SQLModel](session: AsyncSession, model: type[T], id: Any, *, options: list | None = None) -> T:
    result = await session.get(model, id, options=options or [])
    if not result:
        raise ResourceNotFoundError(model.__name__, id)
    return result
