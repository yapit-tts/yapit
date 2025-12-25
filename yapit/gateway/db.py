from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator

from alembic import command, config
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
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
    - PROD (default):                 run Alembic `upgrade head`
    """
    engine = _get_engine(settings)
    if settings.db_drop_and_recreate:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
            await conn.run_sync(SQLModel.metadata.create_all)
    else:
        alembic_cfg = config.Config(str(ALEMBIC_INI))
        # Set absolute path for migrations (relative path in ini doesn't work from /app)
        alembic_cfg.set_main_option("script_location", str(ALEMBIC_INI.parent / "migrations"))
        command.upgrade(alembic_cfg, "head")
    if settings.db_seed:
        await _seed_db(settings)


async def close_db() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def _seed_db(settings: Settings) -> None:
    """Development seed – only runs on an empty DB."""
    from yapit.gateway.dev_seed import seed_dev_database

    async for db in create_session(settings):
        await seed_dev_database(db)
        break  # only iterate once


async def get_or_404[T: SQLModel](session: AsyncSession, model: type[T], id: Any, *, options: list | None = None) -> T:
    result = await session.get(model, id, options=options or [])
    if not result:
        raise ResourceNotFoundError(model.__name__, id)
    return result


async def get_by_slug_or_404[T: SQLModel](session: AsyncSession, model: type[T], slug: str) -> T:
    result = await session.exec(select(model).where(model.slug == slug))
    item = result.first()
    if not item:
        raise ResourceNotFoundError(model.__name__, slug)
    return item
