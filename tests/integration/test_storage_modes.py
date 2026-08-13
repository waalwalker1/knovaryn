"""Storage modes integration tests (spec WP K1).

K1 requires Postgres + S3 support for multi-worker production mode, and that we
do NOT imply SQLite is a safe multi-worker enterprise queue. The local SQLite
path is covered exhaustively by the offline suite; these are **opt-in** live
tests that exercise the Postgres-backed session/queue and the S3-compatible
artifact store against real services.

They skip by default and run only when the corresponding environment variables
are present:

* Postgres: ``KNOVARYN_TEST_POSTGRES_URL`` (e.g. ``postgresql+asyncpg://...``)
* S3: ``KNOVARYN_TEST_S3_ENDPOINT`` + ``KNOVARYN_TEST_S3_ACCESS`` +
  ``KNOVARYN_TEST_S3_SECRET`` + ``KNOVARYN_TEST_S3_BUCKET``

Matching the existing ``live-provider`` contract, these are structural +
round-trip assertions — never truthiness-only (rule 6).
"""

from __future__ import annotations

import asyncio
import hashlib
import os

import pytest

from knovaryn.domain.errors import CorruptedArtifactError
from knovaryn.domain.ids import IdGenerator
from knovaryn.domain.schemas import Project
from knovaryn.infrastructure.database.repositories import (
    ProjectRepository,
)
from knovaryn.infrastructure.database.session import Database

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def run(coro):
    return _LOOP.run_until_complete(coro)


# ---------------------------------------------------------------------------
# PostgreSQL multi-worker-safe backend (K1)
# ---------------------------------------------------------------------------

POSTGRES_URL = os.environ.get("KNOVARYN_TEST_POSTGRES_URL")


@pytest.mark.postgres
@pytest.mark.skipif(not POSTGRES_URL, reason="set KNOVARYN_TEST_POSTGRES_URL")
def test_postgres_session_durable_round_trip():
    """A project written via the async repository is read back across a fresh
    session — the durable shared-DB pattern API/worker rely on."""
    ids = IdGenerator()
    db = Database(POSTGRES_URL)
    try:
        run(db.create_all())

        async def _roundtrip() -> str:
            async with db.session() as session, session.begin():
                repo = ProjectRepository(session, ids)
                await repo.save(
                    Project(
                        id="proj_k1_postgres",
                        slug="k1-postgres",
                        display_name="K1 Postgres",
                        owner_principal="test",
                    )
                )
            async with db.session() as session:
                reloaded = await ProjectRepository(session, ids).get("proj_k1_postgres")
                assert reloaded is not None
                assert reloaded.slug == "k1-postgres"
                assert reloaded.owner_principal == "test"
                return reloaded.id

        assert run(_roundtrip()) == "proj_k1_postgres"
    finally:

        async def _cleanup() -> None:
            async with db.session() as session, session.begin():
                await session.execute(
                    __import__("sqlalchemy").text("DELETE FROM projects WHERE id = :i"),
                    {"i": "proj_k1_postgres"},
                )

        run(_cleanup())
        run(db.dispose())


# ---------------------------------------------------------------------------
# S3-compatible artifact store (K1)
# ---------------------------------------------------------------------------

S3_ENDPOINT = os.environ.get("KNOVARYN_TEST_S3_ENDPOINT")
S3_ACCESS = os.environ.get("KNOVARYN_TEST_S3_ACCESS")
S3_SECRET = os.environ.get("KNOVARYN_TEST_S3_SECRET")
S3_BUCKET = os.environ.get("KNOVARYN_TEST_S3_BUCKET")

_S3_REQUIRED = all([S3_ENDPOINT, S3_ACCESS, S3_SECRET, S3_BUCKET])


def _s3_store():
    from knovaryn.infrastructure.artifacts.s3 import S3ArtifactStore

    return S3ArtifactStore(
        bucket=S3_BUCKET,
        endpoint_url=S3_ENDPOINT,
        access_key_id=S3_ACCESS,
        secret_access_key=S3_SECRET,
        region="us-east-1",
    )


@pytest.mark.s3
@pytest.mark.skipif(not _S3_REQUIRED, reason="set KNOVARYN_TEST_S3_*")
def test_s3_artifact_put_get_round_trip():
    store = _s3_store()
    payload = b"knovaryn s3 content-addressed artifact"
    manifest = run(
        store.put(
            payload,
            media_type="application/octet-stream",
            producer={"component": "test-k1", "version": "0"},
        )
    )
    # content-addressed: id + sha256 both resolve to the same bytes
    sha = hashlib.sha256(payload).hexdigest()
    assert manifest["sha256"] == sha
    assert run(store.get(manifest["artifact_id"])) == payload
    assert run(store.get(sha)) == payload


@pytest.mark.s3
@pytest.mark.skipif(not _S3_REQUIRED, reason="set KNOVARYN_TEST_S3_*")
def test_s3_artifact_corruption_caught():
    """A stored object whose bytes differ from its content hash must be flagged
    (fail closed, rule 6) rather than silently returned."""
    store = _s3_store()
    original = b"integrity-checkable payload"
    manifest = run(
        store.put(
            original,
            media_type="text/plain",
            producer={"component": "test-k1", "version": "0"},
        )
    )
    sha = manifest["sha256"]
    blobj = f"objects/{sha[:2]}/{sha}"

    # Seed a tampered blob under the object key so the index points at bytes
    # that no longer match the content hash.
    async def _tamper() -> None:
        async with store._client() as s3:  # noqa: SLF001 - test fixture
            await s3.put_object(Bucket=S3_BUCKET, Key=blobj, Body=b"TAMPERED")

    run(_tamper())
    with pytest.raises(CorruptedArtifactError):
        run(store.get(sha))
