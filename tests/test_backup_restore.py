"""Backup/restore tests (spec §23.1, WP K5).

Builds a real SQLite DB (with content) + a small content-addressed artifact
store, takes a backup snapshot, restores it into a clean directory, and asserts
referential integrity + checksum verification. Also verifies a tampered blob is
caught (fail closed) and the detached archive checksum matches.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from knovaryn.deployment.backup import build_backup, restore_backup
from knovaryn.domain.errors import CorruptedArtifactError


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, slug TEXT)")
    conn.execute("CREATE TABLE examples (id TEXT PRIMARY KEY, project_id TEXT)")
    conn.execute("INSERT INTO projects VALUES ('p1','demo'), ('p2','other')")
    conn.execute("INSERT INTO examples VALUES ('e1','p1')")
    conn.commit()
    conn.close()


def _make_artifacts(root: Path) -> None:
    blob = root / "objects" / "ab"
    blob.mkdir(parents=True, exist_ok=True)
    (blob / "abc123").write_bytes(b"hello world content")
    (root / "manifests").mkdir(parents=True, exist_ok=True)
    (root / "manifests" / "abc.manifest.json").write_text(
        json.dumps({"object_id": "abc123", "sha256": "abc"})
    )


@pytest.fixture
def data(tmp_path):
    db = tmp_path / "state" / "knovaryn.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    _make_db(db)
    art = tmp_path / "state" / "artifacts"
    _make_artifacts(art)
    return {"db": db, "art": art, "state": tmp_path / "state"}


def test_backup_restore_round_trip(data, tmp_path):
    out = tmp_path / "backup.zip"
    res = build_backup(
        database_url=f"sqlite+aiosqlite:///{data['db']}",
        artifact_root=data["art"],
        out_path=out,
    )
    assert out.exists() and res["files"] >= 2
    # detached checksum matches the archive bytes
    detached = Path(str(out) + ".sha256").read_text().strip()
    import hashlib

    assert detached == hashlib.sha256(out.read_bytes()).hexdigest()

    # restore into a clean dir
    r = restore_backup(archive=out, dest_dir=tmp_path / "clean")
    assert r["integrity_verified"] is True
    # DB restored and referentially intact (both tables read)
    conn = sqlite3.connect(tmp_path / "clean" / "db" / "knovaryn.db")
    assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM examples WHERE project_id='p1'").fetchone()[0] == 1
    conn.close()
    # artifact blob restored with matching checksum
    restored_blob = tmp_path / "clean" / "artifacts" / "objects" / "ab" / "abc123"
    assert restored_blob.read_bytes() == b"hello world content"


def test_restore_detects_tampered_blob(data, tmp_path):
    out = tmp_path / "bak.zip"
    build_backup(
        database_url=f"sqlite+aiosqlite:///{data['db']}",
        artifact_root=data["art"],
        out_path=out,
    )
    import zipfile

    # tamper one entry in place (rewrite with a corrupted db file)
    tmp = tmp_path / "tampered.zip"
    with zipfile.ZipFile(out) as zin, zipfile.ZipFile(tmp, "w") as zout:
        for item in zin.infolist():
            payload = zin.read(item.filename)
            if item.filename == "db/knovaryn.db":
                payload = b"corrupted-not-a-real-db"
            zout.writestr(item, payload)
    with pytest.raises(CorruptedArtifactError):
        restore_backup(archive=tmp, dest_dir=tmp_path / "clean2")


def test_restore_requires_manifest(data, tmp_path):
    out = tmp_path / "bak.zip"
    build_backup(
        database_url=f"sqlite+aiosqlite:///{data['db']}",
        artifact_root=data["art"],
        out_path=out,
    )
    import zipfile

    tmp = tmp_path / "no-manifest.zip"
    with zipfile.ZipFile(out) as zin, zipfile.ZipFile(tmp, "w") as zout:
        for item in zin.infolist():
            if item.filename != "backup-manifest.json":
                zout.writestr(item, zin.read(item.filename))
    with pytest.raises(CorruptedArtifactError):
        restore_backup(archive=tmp, dest_dir=tmp_path / "clean3")
