from collections.abc import AsyncIterator

from alembic import command, config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.config import ANON_USER, get_settings
from yapit.gateway.domain_models import Model, User, Voice

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


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


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
    async with SessionLocal() as db:
        if not (await db.execute(select(User).where(User.id == ANON_USER.id))).first():
            db.add(ANON_USER)
        voice_exists = await db.execute(select(Model.id).where(Model.slug == "kokoro"))
        if not voice_exists.first():
            model = Model(slug="kokoro", name="Kokoro", price_sec=0.0)
            voice = Voice(model=model, slug="af_heart", name="af_heart", lang="af")
            db.add_all([model, voice])
        await db.commit()
