"""Additive column migration (defect 3.7, v0.2.1).

``create_all`` historically only created missing *tables*. When v0.2.1 adds
columns to ``source_spans`` (page_start / page_end / bounding_boxes /
precision), a database created by v0.2.0 must upgrade in place — otherwise the
first pipeline run after an in-place upgrade fails with ``undefined column``.
These tests pin that contract:

1. a v0.2.0-shaped table + existing rows upgrades without loss;
2. backfilled rows carry the model's own defaults (precision='unknown');
3. new spans persist and read back with full precision fields intact.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from knovaryn.domain.schemas import SpanPrecision, SourceSpan
from knovaryn.infrastructure.database.repositories import SpanRepository
from knovaryn.infrastructure.database.session import Database

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture()
def upgraded_db(tmp_path):
    """A sqlite file whose source_spans table has the OLD (v0.2.0) shape,
    containing one legacy row, then migrated by create_all."""
    path = tmp_path / "legacy.db"

    # 1. simulate the v0.2.0 schema exactly (no new columns)
    legacy = Database(f"sqlite+aiosqlite:///{path}")
    try:

        async def make_legacy():
            async with legacy.engine.begin() as conn:
                await conn.execute(text(
                    "CREATE TABLE source_spans ("
                    " id VARCHAR(64) PRIMARY KEY,"
                    " parsed_document_id VARCHAR(64) NOT NULL,"
                    " page_number INTEGER,"
                    " section_path VARCHAR(1024),"
                    " element_reference VARCHAR(255),"
                    " character_start INTEGER,"
                    " character_end INTEGER,"
                    " quoted_text TEXT,"
                    " sha256 VARCHAR(64) NOT NULL)"
                ))
                await conn.execute(text(
                    "INSERT INTO source_spans VALUES "
                    "('span-legacy','doc-1',3,'','elem-9',10,20,'quoted','abc')"
                ))

        run(make_legacy())
    finally:
        run(legacy.dispose())

    # 2. open with current models -> create_all must migrate the table
    db = Database(f"sqlite+aiosqlite:///{path}")
    run(db.create_all())
    yield db
    run(db.dispose())


def _columns(db: Database) -> dict:
    def _go(sync_conn):
        from sqlalchemy import inspect

        insp = inspect(sync_conn)
        return {c["name"] for c in insp.get_columns("source_spans")}

    return run(_run_sync(db, _go))


def _run_sync(db: Database, fn):
    async def go():
        async with db.engine.begin() as conn:
            return await conn.run_sync(fn)

    return go()


def test_upgrade_adds_new_columns_with_backfill(upgraded_db: Database) -> None:
    cols = _columns(upgraded_db)
    for name in ("page_start", "page_end", "bounding_boxes", "precision"):
        assert name in cols, f"migration did not add {name}; got {sorted(cols)}"

    rows = run(_raw_rows(upgraded_db))
    assert len(rows) == 1
    legacy = dict(rows[0]._mapping)
    # legacy row survived ...
    assert legacy["id"] == "span-legacy"
    assert legacy["page_number"] == 3
    # ... and was backfilled with the model's own defaults
    assert legacy["precision"] == "unknown"
    assert legacy["bounding_boxes"] in ("[]", b"[]", [])


def test_migrated_table_accepts_full_precision_spans(upgraded_db: Database) -> None:
    async def go():
        async with upgraded_db.session() as s:
            repo = SpanRepository(s)
            span = SourceSpan(
                id="span-full-precision",
                parsed_document_id="doc-2",
                page_number=4,
                bounding_boxes=[{
                    "page": 4, "left": 10.0, "top": 20.0, "right": 110.0,
                    "bottom": 40.0, "coord_origin": "TOPLEFT", "coord_system": "page",
                }],
                quoted_text="torqued to 5 N·m",
                sha256="deadbeef",
            ).with_derived_precision()
            await repo.add(span)
            await s.commit()  # ensure the added span is persisted

        async with upgraded_db.session() as s:
            return await SpanRepository(s).get(span.id)

    loaded = run(go())
    assert loaded is not None
    assert loaded.precision is SpanPrecision.exact_bbox
    assert loaded.page_number == 4
    assert loaded.bounding_boxes and loaded.bounding_boxes[0]["page"] == 4
    assert loaded.quoted_text == "torqued to 5 N·m"


def test_migration_is_idempotent(upgraded_db: Database) -> None:
    run(upgraded_db.create_all())
    run(upgraded_db.create_all())  # second pass must be a no-op, not an error
    cols = _columns(upgraded_db)
    assert "precision" in cols


def _raw_rows(db: Database):
    async def go():
        async with db.engine.begin() as conn:
            res = await conn.execute(text("SELECT * FROM source_spans"))
            return res.fetchall()

    return go()
