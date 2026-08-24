"""Async engine/session helpers (spec §21.1).

SQLite uses WAL mode, foreign keys on, and documented local concurrency.
PostgreSQL via asyncpg. Provides an async session factory and a tiny
scope/transaction helper used by repositories and application services.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from .models import Base


def _sqlite_onconnect(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


def create_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    url = make_url(database_url)
    kwargs: dict = {"echo": echo}
    if url.drivername.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        # NullPool for SQLite/aiosqlite (defect 3.2): a default pool keeps idle
        # aiosqlite connections open until engine disposal. Lifespans are often
        # torn down inside an already-cancelled anyio scope (MCP task groups,
        # client disconnects), and a pooled-connection close that gets cancelled
        # mid-await leaves unresolved op futures on the aiosqlite worker thread,
        # which then raise ``RuntimeError('Event loop is closed')`` after loop
        # shutdown. With NullPool every connection closes deterministically when
        # its session context exits — inside normal request scope — so there is
        # nothing left dangling at disposal time.
        kwargs["poolclass"] = NullPool
    engine = create_async_engine(database_url, **kwargs)
    if url.drivername.startswith("sqlite"):
        # apply PRAGMAs on the raw sync connection (async engine uses aiosqlite)
        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn: Any, conn_record: Any) -> None:
            _sqlite_onconnect(dbapi_conn, conn_record)

    return engine


def _sql_default_literal(column: Any) -> str | None:
    """SQL literal for backfilling an added column, or None if unavailable."""
    if column.server_default is not None and isinstance(
        getattr(column.server_default, "arg", None), str
    ):
        return "'" + str(column.server_default.arg).replace("'", "''") + "'"
    arg = getattr(column.default, "arg", None) if column.default is not None else None
    if arg is None:
        return None
    if callable(arg):
        # Newer SQLAlchemy wraps python-side callables
        # (CallableColumnDefault._maybe_wrap_callable -> update_wrapper),
        # so recover the original factory from __wrapped__ when present.
        fn = getattr(arg, "__wrapped__", arg)
        # zero-arg factories used across this project's models
        if fn in (list, tuple, set):
            return "'[]'"
        if fn is dict:
            return "'{}'"
        return None  # unknown factory: refuse to guess
    if isinstance(arg, bool):
        return str(int(arg))
    if isinstance(arg, (int, float)):
        return str(arg)
    if isinstance(arg, str):
        return "'" + arg.replace("'", "''") + "'"
    return None


def _add_missing_columns(sync_conn: Any) -> None:
    """Idempotent lightweight column migration (v0.2.1).

    ``create_all`` only creates missing *tables*; columns added to an existing
    model in a later release would silently break inserts against databases
    created by older versions. For every mapped column missing from the live
    table this issues ``ALTER TABLE ... ADD COLUMN``, deriving a SQL default
    from the model's own default so existing rows backfill. Additive-only and
    non-destructive: no data is rewritten, nothing is dropped.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            coltype = column.type.compile()
            literal = _sql_default_literal(column)
            if literal is not None:
                suffix = f" DEFAULT {literal}"
            elif column.nullable:
                suffix = " DEFAULT NULL"
            else:
                raise RuntimeError(
                    f"cannot migrate: {table.name}.{column.name} is NOT NULL with "
                    "no derivable default; add an explicit server_default or "
                    "make it nullable before shipping the schema change"
                )
            sync_conn.execute(
                text(f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {coltype}{suffix}')
            )


class Database:
    def __init__(self, database_url: str, *, echo: bool = False) -> None:
        self.engine = create_engine(database_url, echo=echo)
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def create_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_add_missing_columns)

    async def dispose(self) -> None:
        # Shielded (defect 3.2): teardown frequently runs inside an
        # already-cancelled anyio scope; once disposal starts it must run to
        # completion, otherwise pooled connections (Postgres) can be left with
        # unresolved futures that surface as worker-thread errors after loop
        # shutdown.
        await asyncio.shield(self.engine.dispose())

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session
