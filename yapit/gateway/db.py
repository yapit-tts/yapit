import json
from pathlib import Path
from typing import AsyncIterator

from alembic import command, config
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.config import Settings
from yapit.gateway.domain_models import (
    Filter,
    TTSModel,
    Voice,
)

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
        alembic_cfg = config.Config("alembic.ini")
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
    async for db in create_session(settings):
        kokoro_cpu = TTSModel(
            slug="kokoro-cpu",
            name="Kokoro (CPU)",
            price_sec=0.0,
            native_codec="pcm",
            sample_rate=24_000,
            channels=1,
            sample_width=2,
        )
        voices_json = Path(__file__).parent.parent / "workers/kokoro/voices.json"
        for v in json.loads(voices_json.read_text()):
            kokoro_cpu.voices.append(
                Voice(
                    slug=v["index"],
                    name=v["name"],
                    lang=v["language"],
                    description=f"Quality grade {v['overallGrade']}",
                )
            )
        db.add(kokoro_cpu)
        # dia = Model(
        #     slug="dia",
        #     name="Dia-1.6B",
        #     price_sec=0.0,
        #     native_codec="pcm",
        #     sample_rate=44_100,
        #     channels=1,
        #     sample_width=2,
        # )
        # dia.voices.append(Voice(slug="default", name="Dia", lang="en")
        # db.add(dia)

        presets_json = Path(__file__).parent.parent / "data/default_filters.json"
        defaults = json.loads(presets_json.read_text())
        for p in defaults:
            db.add(
                Filter(
                    name=p["name"],
                    description=p.get("description"),
                    config=p["config"],
                    user_id=None,  # system filters
                )
            )
        await db.commit()
        break  # only iterate once
