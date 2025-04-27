import os
from collections.abc import AsyncIterator

from alembic import command, config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

from gateway.config import ANON_USER, get_settings
from gateway.domain.models import User

# TODO collect all env vars centrally in Settings and use settings here

settings = get_settings()
engine = create_async_engine(
    settings.database_url,
    echo=os.getenv("SQLALCHEMY_ECHO") == "1",
    pool_pre_ping=True,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def prepare_database() -> None:
    """Bring the schema to the requested state.

    - DEV (DB_AUTO_CREATE=1):   create missing tables on the fly
    - PROD (default):           run Alembic `upgrade head`
    """
    if os.getenv("DB_AUTO_CREATE") == "1":
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
    else:
        alembic_cfg = config.Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
    if os.getenv("DB_SEED") == "1":
        await _seed_db()


async def close_db() -> None:
    await engine.dispose()


async def _seed_db() -> None:
    async with SessionLocal() as db:
        if not (await db.execute(select(User).where(User.id == ANON_USER.id))).first():
            db.add(ANON_USER)
            await db.commit()
