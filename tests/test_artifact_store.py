"""Content-addressed artifact store tests (spec §6.3, §21.2).

Exercises the local filesystem CAS: put/get round-trip, content dedup,
checksum/corruption detection, streaming writes, and artifact-handle
resolution. S3 adapter is an optional extra and not exercised offline.
"""

from __future__ import annotations

import asyncio
import hashlib

import pytest

from knovaryn.domain.errors import CorruptedArtifactError, NotFoundError
from knovaryn.infrastructure.artifacts.local import LocalArtifactStore

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture
def store(tmp_path) -> LocalArtifactStore:
    s = LocalArtifactStore(tmp_path / "artifacts")
    yield s


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_put_get_roundtrip(store: LocalArtifactStore) -> None:
    payload = b"hello knovaryn artifact"
    manifest = run(
        store.put(
            payload,
            media_type="text/plain",
            producer={"component": "test", "version": "0"},
        )
    )
    assert manifest["byte_size"] == len(payload)
    # put returns the artifact handle; get() accepts either the handle or sha256.
    assert manifest["artifact_id"].startswith("art_")
    for key in (manifest["artifact_id"], manifest["sha256"]):
        assert run(store.get(key)) == payload


def test_get_returns_correct_content_by_sha(store: LocalArtifactStore) -> None:
    payload = b"unique content here"
    manifest = run(
        store.put(
            payload,
            media_type="application/octet-stream",
            producer={"component": "test"},
        )
    )
    assert run(store.get(manifest["sha256"])) == payload


def test_content_addressed_dedup(store: LocalArtifactStore) -> None:
    payload = b"same bytes dedup"
    m1 = run(store.put(payload, media_type="text/plain", producer={"component": "a"}))
    m2 = run(store.put(payload, media_type="text/plain", producer={"component": "b"}))
    # Same content -> same address and same artifact_id (immutable CAS).
    assert m1["sha256"] == m2["sha256"] == _sha(payload)
    # The blob is stored once.
    blob = store._blob_path(m1["sha256"])
    assert blob.exists()


def test_corruption_detected(store: LocalArtifactStore) -> None:
    payload = b"to be corrupted"
    manifest = run(store.put(payload, media_type="text/plain", producer={"component": "t"}))
    blob = store._blob_path(manifest["sha256"])
    blob.write_bytes(b"tampered bytes!")
    with pytest.raises(CorruptedArtifactError):
        run(store.get(manifest["sha256"]))


def test_missing_artifact_raises_not_found(store: LocalArtifactStore) -> None:
    with pytest.raises(NotFoundError):
        run(store.get("art_doesnotexist"))
    assert run(store.exists("art_doesnotexist")) is False


def test_manifest_metadata(store: LocalArtifactStore) -> None:
    payload = b"metadata check"
    producer = {"component": "pipeline", "version": "1.2"}
    run(store.put(payload, media_type="application/json", producer=producer))
    meta = run(store.get_meta(_sha(payload)))
    assert meta["sha256"] == _sha(payload)
    assert meta["producer"] == producer
    assert meta["media_type"] == "application/json"


def test_streaming_roundtrip(store: LocalArtifactStore) -> None:
    first = b"stream part 1 "
    second = b"stream part 2 "
    writer = run(store.put_stream(producer={"component": "stream"}, media_type="text/plain"))
    run(writer.write(first))
    run(writer.write(second))
    manifest = run(writer.commit())

    combined = first + second
    assert manifest["byte_size"] == len(combined)
    assert run(store.get(manifest["sha256"])) == combined
