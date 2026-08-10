"""Alembic migration baseline tests (spec §21.1).

The schema contract: from a clean database, ``alembic upgrade head`` produces
exactly the tables the ORM metadata declares (no drift), and ``downgrade base``
fully reverses it. These tests lock the migration baseline against the live
models so a future model change without a matching migration fails CI rather
than silently drifting.

Uses the real migration environment (``migrations/env.py``) against a
temporary SQLite database so it exercises the same async path the application
uses.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig

from knovaryn.infrastructure.database.models import Base

REPO_ROOT = Path(__file__).resolve().parents[1]


def _config(database_url: str) -> AlembicConfig:
    cfg = AlembicConfig(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'mig.db'}"


def _sync_path(database_url: str) -> str:
    """Return the file path of an sqlite+aiosqlite URL for sync inspection."""
    prefix = "sqlite+aiosqlite:///"
    assert database_url.startswith(prefix), "migration tests assume sqlite"
    return database_url[len(prefix) :]


def _table_names(database_url: str) -> set[str]:
    import sqlite3

    con = sqlite3.connect(_sync_path(database_url))
    try:
        rows = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    finally:
        con.close()
    return {row[0] for row in rows}


def test_upgrade_head_creates_full_metadata_schema(db_url: str) -> None:
    command.upgrade(_config(db_url), "head")

    existing = _table_names(db_url)
    declared = set(Base.metadata.tables.keys())
    # alembic_version is managed by alembic, not the ORM metadata.
    assert existing == declared | {"alembic_version"}


def test_models_match_baseline_no_drift(db_url: str) -> None:
    """After upgrade, autogenerate against the models must report no diff."""
    command.upgrade(_config(db_url), "head")

    import sqlalchemy as sa
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    # Inspect the migrated file with a plain sync engine (the file already
    # holds the upgraded schema), so no async greenlet plumbing is needed.
    engine = sa.create_engine(f"sqlite:///{_sync_path(db_url)}")
    with engine.connect() as conn:
        migration_context = MigrationContext.configure(conn, opts={"compare_type": True})
        drift = compare_metadata(migration_context, Base.metadata)
    engine.dispose()

    assert drift == [], f"Migration baseline drifted from models: {drift}"


def test_roundtrip_downgrade_base_reversible(db_url: str) -> None:
    command.upgrade(_config(db_url), "head")
    command.downgrade(_config(db_url), "base")

    existing = _table_names(db_url)
    assert existing == {"alembic_version"}
