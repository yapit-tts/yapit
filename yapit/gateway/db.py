from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from alembic import command, config
from loguru import logger
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.config import Settings
from yapit.gateway.exceptions import ResourceNotFoundError
from yapit.gateway.seed import seed_database, sync_inworld_voices

ALEMBIC_INI = Path(__file__).parent / "alembic.ini"

# Revision just before the selfhost baseline migration. Legacy self-host databases
# (created via create_all, no alembic_version table) get stamped here so that
# upgrade head only runs the baseline + any future migrations.
_SELFHOST_BASELINE_PARENT = "86c4c0dd6eeb"

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_db(settings: Settings) -> None:
    """Initialize the database engine and session factory. Call once at startup."""
    global _engine, _session_factory
    if _engine is not None:
        return
    _engine = create_async_engine(
        settings.database_url,
        echo=settings.sqlalchemy_echo,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
    _session_factory = async_sessionmaker(
        _engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )


@asynccontextmanager
async def create_session() -> AsyncIterator[AsyncSession]:
    assert _session_factory is not None, "Database not initialized — call init_db() first"
    async with _session_factory() as session:
        yield session


async def prepare_database(settings: Settings) -> None:
    """Bring the schema to the requested state.

    - DEV (DB_DROP_AND_RECREATE=1):  drop all tables and recreate from scratch
    - Everything else:               Alembic `upgrade head`

    Legacy self-host databases (created via create_all, no alembic_version table)
    are detected and stamped so that only the baseline migration runs.
    """
    assert _engine is not None, "Database not initialized — call init_db() first"
    if settings.db_drop_and_recreate:
        async with _engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
            await conn.run_sync(SQLModel.metadata.create_all)
    else:
        alembic_cfg = config.Config(str(ALEMBIC_INI))
        alembic_cfg.set_main_option("script_location", str(ALEMBIC_INI.parent / "migrations"))

        async with _engine.connect() as conn:
            has_alembic = await conn.run_sync(_table_exists, "alembic_version")
            has_tables = await conn.run_sync(_table_exists, "document")

        if not has_alembic and has_tables:
            logger.info("Legacy self-host database detected — transitioning to Alembic")
            await asyncio.to_thread(command.stamp, alembic_cfg, _SELFHOST_BASELINE_PARENT)

        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
    if settings.db_seed:
        await _seed_db(settings)
    await _sync_voices()


def _table_exists(connection, table_name: str) -> bool:
    return inspect(connection).has_table(table_name)


def get_engine() -> AsyncEngine:
    """Return the initialized engine. For use in tests and tooling."""
    assert _engine is not None, "Database not initialized — call init_db() first"
    return _engine


async def close_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


async def _seed_db(settings: Settings) -> None:
    async with create_session() as db:
        await seed_database(db, settings)


async def _sync_voices() -> None:
    async with create_session() as db:
        await sync_inworld_voices(db)


async def get_or_404[T: SQLModel](session: AsyncSession, model: type[T], id: Any, *, options: list | None = None) -> T:
    result = await session.get(model, id, options=options or [])
    if not result:
        raise ResourceNotFoundError(model.__name__, id)
    return result
