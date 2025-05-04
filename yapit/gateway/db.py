import json
from pathlib import Path

from alembic import command, config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.config import ANON_USER, get_settings
from yapit.gateway.domain_models import Model, Voice

settings = get_settings()
engine = create_async_engine(
    settings.database_url,
    echo=settings.sqlalchemy_echo,
    pool_pre_ping=True,
)
SessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def prepare_database() -> None:
    """Bring the schema to the requested state.

    - DEV (DB_AUTO_CREATE=1):   create missing tables on the fly
    - PROD (default):           run Alembic `upgrade head`
    """
    if settings.db_auto_create:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
    else:
        alembic_cfg = config.Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
    if settings.db_seed:
        await _seed_db()


async def close_db() -> None:
    await engine.dispose()


async def _seed_db() -> None:
    # dev db seed - populate empty db
    async with SessionLocal() as db:
        db.add(ANON_USER)
        kokoro = Model(
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
        db.add_all(
            [
                kokoro,
                # dia
            ]
        )
        await db.commit()
