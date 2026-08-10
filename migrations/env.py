"""Alembic migration environment (spec §21.1).

The application uses asynchronous SQLAlchemy engines (aiosqlite locally,
asyncpg for PostgreSQL), so the migration environment runs the migration
against the async engine. The database URL is resolved from Knovaryn
configuration the same way the application resolves it:

- default ``sqlite+aiosqlite:///./.knovaryn/knovaryn.db``;
- overridable via ``KNOVARYN_STORAGE_DATABASE_URL`` (or the nested
  ``${ENV}``-style placeholder in a project/user config file).

Run from the repository root::

    alembic upgrade head
    alembic revision --autogenerate -m "describe change"
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import async_engine_from_config

from knovaryn.infrastructure.database import models  # noqa: F401  (registers tables)
from knovaryn.infrastructure.database.models import Base

# Alembic Config object, which provides access to the values within the .ini file.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Populate the configured sqlalchemy.url from Knovaryn config unless the user
# supplied an override on the command line (--sqlalchemy.url=...).
_target_metadata = Base.metadata


def _resolve_database_url(url: object | None) -> str:
    """Resolve the effective database URL from Knovaryn configuration."""
    if url:
        return str(url)
    # KNOVARYN_STORAGE_DATABASE_URL -> storage.database_url
    env_url = os.environ.get("KNOVARYN_STORAGE_DATABASE_URL")
    if env_url:
        return env_url
    return "sqlite+aiosqlite:///./.knovaryn/knovaryn.db"


def _sync_create_schema(connection: Connection) -> None:
    """Used for offline (--sql) generation: emit the full target schema."""
    _target_metadata.create_all(connection)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode; emit SQL to stdout."""
    url = _resolve_database_url(config.get_main_option("sqlalchemy.url"))
    context.configure(
        url=make_url(url).render_as_string(hide_password=False),
        target_metadata=_target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=_target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations against the async engine in online mode."""
    url = _resolve_database_url(config.get_main_option("sqlalchemy.url"))
    config.set_main_option("sqlalchemy.url", url)
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
