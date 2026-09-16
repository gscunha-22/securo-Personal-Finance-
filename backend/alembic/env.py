import asyncio
from logging.config import fileConfig

from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool

from alembic import context

from app.core.database import Base, alembic_database_url, create_engine_from_url
from app.models import *  # noqa: F401,F403
# Agents module models (always loaded so migrations stay in sync; the
# feature itself is gated at runtime by AGENTS_ENABLED).
from app.agents.models import *  # noqa: F401,F403

config = context.config

config.set_main_option("sqlalchemy.url", alembic_database_url().replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_engine_from_url(
        alembic_database_url(),
        poolclass=NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
