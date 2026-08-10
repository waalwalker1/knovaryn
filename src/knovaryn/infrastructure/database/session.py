"""Async engine/session helpers (spec §21.1).

SQLite uses WAL mode, foreign keys on, and documented local concurrency.
PostgreSQL via asyncpg. Provides an async session factory and a tiny
scope/transaction helper used by repositories and application services.
"""

from __future__ import annotations

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
    engine = create_async_engine(database_url, **kwargs)
    if url.drivername.startswith("sqlite"):
        # apply PRAGMAs on the raw sync connection (async engine uses aiosqlite)
        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn: Any, conn_record: Any) -> None:
            _sqlite_onconnect(dbapi_conn, conn_record)

    return engine


class Database:
    def __init__(self, database_url: str, *, echo: bool = False) -> None:
        self.engine = create_engine(database_url, echo=echo)
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def create_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session
