import json
from pathlib import Path
from typing import AsyncIterator

from alembic import command, config
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.config import Settings, get_settings
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

    - DEV (DB_AUTO_CREATE=1):   create missing tables on the fly
    - PROD (default):           run Alembic `upgrade head`
    """
    engine = _get_engine(settings)
    if settings.db_auto_create:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
    else:
        alembic_cfg = config.Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
    if settings.db_seed:
        await _seed_db(settings)


async def close_db() -> None:
    if _engine is not None:
        await _engine.dispose()


async def _seed_db(settings: Settings) -> None:
    """Development seed – only runs on an empty DB."""
    db = await anext(create_session(settings))
    kokoro = TTSModel(
        slug="kokoro",
        name="Kokoro",
        price_sec=0.0,
        native_codec="pcm",
        sample_rate=24_000,
        channels=1,
        sample_width=2,
    )
    voices_json = Path(__file__).parent.parent / "workers/kokoro/voices.json"
    for v in json.loads(voices_json.read_text()):
        kokoro.voices.append(
            Voice(
                slug=v["index"],
                name=v["name"],
                lang=v["language"],
                description=f"Quality grade {v['overallGrade']}",
            )
        )
    db.add(kokoro)
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
        print(f"{p}")
        db.add(
            Filter(
                name=p["name"],
                description=p.get("description"),
                config=p["config"],
            )
        )
    await db.commit()
