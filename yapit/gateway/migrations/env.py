import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

# Import all models so SQLModel.metadata is populated
from yapit.gateway import domain_models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

# Tables we manage - everything else (like Stack Auth tables) is ignored
MANAGED_TABLES = {table.name for table in target_metadata.sorted_tables}


def include_object(object, name, type_, reflected, compare_to):
    """Only include objects that are part of our models."""
    if type_ == "table":
        return name in MANAGED_TABLES
    # For indexes/constraints, check if parent table is managed
    if hasattr(object, "table") and object.table is not None:
        return object.table.name in MANAGED_TABLES
    return True


def get_url() -> str:
    """Get database URL from environment, converting async driver to sync."""
    url = os.environ.get("DATABASE_URL", "")
    # Alembic needs sync driver - convert asyncpg to psycopg
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
