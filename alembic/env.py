import asyncio
from logging.config import fileConfig

from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Make the app importable and pull in metadata + settings
from app.core.config import settings
from app.db.base import Base
import app.db.models  # noqa: F401  (registers all models on Base.metadata)

config = context.config

# Drive the DB URL from app settings (single source of truth), not alembic.ini
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# Objects created by raw SQL that the models can't express (expression indexes
# over sotuvchi_norm(), GIN trgm ops). Without this, autogenerate reads them as
# stray and writes DROPs into the next migration — which is exactly how catalog
# search was silently deleted once already.
RAW_SQL_INDEXES = {
    "ix_products_search_trgm",
    "ix_products_name_trgm",
    "ix_products_tenant_cat_price",
}


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "index" and name in RAW_SQL_INDEXES:
        return False
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # Rolling deploys may start several containers at once. Take the lock inside
    # Alembic's migration transaction; PostgreSQL releases it automatically when
    # the transaction commits.
    lock_id = 7_364_895_201
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        connection.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": lock_id})
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
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
