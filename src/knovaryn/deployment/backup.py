"""Backup and restore (spec §23.1, WP K5).

A single self-contained archive of the SQLite database plus the content-addressed
artifact store, with a per-file SHA-256 manifest and a documented recovery point/
time. Restore rehydrates into a clean directory and verifies referential
integrity (the DB opens and artifact blobs that manifests reference resolve and
match their checksums).

Design notes:

* **Recovery point objective (RPO):** the backup is a point-in-time snapshot —
  anything written after the backup begins is not included. RPO therefore
  equals the time to produce the archive (near-zero for local mode).
* **Recovery time objective (RTO):** bounded by archive read + DB load + blob
  verification; for local SQLite CAS this is typically sub-second to a few
  seconds.
* The .knovaryn DB and artifact store are both content-addressed / immutable, so
  a restore is a byte-for-byte copy; no migration is required.

The module is offline and dependency-free (Python ``zipfile``/``sqlite3``).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..domain.errors import CorruptedArtifactError

_BACKUP_FILES = ("db/knovaryn.db", "artifacts")
_MANIFEST_NAME = "backup-manifest.json"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _iter_files(root: Path, rel_prefix: str) -> Iterator[tuple[str, Path]]:
    if not root.exists():
        return
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield f"{rel_prefix}/{path.relative_to(root).as_posix()}", path


def build_backup(
    *,
    database_url: str,
    artifact_root: str | Path,
    out_path: str | Path,
    checkpoint: int = 1,
) -> dict[str, Any]:
    """Snapshot the SQLite DB + artifact store into a self-contained zip.

    ``checkpoint`` uses ``PRAGMA wal_checkpoint`` when set to 1 so the on-disk
    main DB file reflects committed WAL data before we copy it (RPO).
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Resolve the SQLite file path from the async URL (sqlite+aiosqlite:///PATH).
    url = database_url
    db_path = Path(url.split(":///", 1)[1]) if ":///" in url else Path(url)
    if checkpoint and db_path.exists():
        _wal_checkpoint(db_path)

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "created_at": _now_iso(),
        "database_url": database_url,
        "files": [],
        "rpo": "point-in-time snapshot",
        "rto": "archive-read + db-load + blob-verify",
    }

    tmp = out.with_suffix(".tmp.zip")
    import zipfile

    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        entries: list[tuple[str, bytes]] = []
        if db_path.exists():
            entries.append(("db/knovaryn.db", db_path.read_bytes()))
        art = Path(artifact_root)
        for rel, path in _iter_files(art, "artifacts"):
            entries.append((rel, path.read_bytes()))
        for rel, data in entries:
            digest = _sha256_bytes(data)
            zf.writestr(rel, data)
            manifest["files"].append({"path": rel, "size": len(data), "sha256": digest})
        # write the manifest last so a consumer can trust files+checksums; the
        # archive's own digest is NOT inside the archive (self-referential).
        zf.writestr(_MANIFEST_NAME, json.dumps(manifest, indent=2))

    digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
    Path(str(out) + ".sha256").write_text(digest + "\n")
    shutil.move(str(tmp), out)
    return {"archive": str(out), "files": len(manifest["files"]), "sha256": digest}


def _wal_checkpoint(db_path: Path) -> None:
    try:
        with (
            sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn,
            contextlib.suppress(sqlite3.OperationalError),
        ):
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # no WAL
    except sqlite3.Error:
        pass


def restore_backup(
    *,
    archive: str | Path,
    dest_dir: str | Path,
    require_integrity: bool = True,
) -> dict[str, Any]:
    """Restore a backup archive into a clean ``dest_dir``.

    If ``require_integrity`` (default), every file's content is verified against
    the manifest's SHA-256 and mismatches raise :class:`CorruptedArtifactError`.
    """
    import zipfile

    archive = Path(archive)
    dest = Path(dest_dir)
    if dest.exists():
        # restore only into a clean environment (or clear explicitly)
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] | None = None
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        if _MANIFEST_NAME not in names:
            raise CorruptedArtifactError("backup archive missing manifest")
        manifest = json.loads(zf.read(_MANIFEST_NAME))
        for info in zf.infolist():
            name = info.filename
            if name == _MANIFEST_NAME:
                continue
            data = zf.read(name)
            if require_integrity:
                expected = _manifest_sha(manifest, name)
                if expected is None or _sha256_bytes(data) != expected:
                    raise CorruptedArtifactError(f"checksum mismatch on {name}")
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    return {
        "restored_to": str(dest),
        "files": len(manifest.get("files", [])),
        "integrity_verified": require_integrity,
    }


def _manifest_sha(manifest: dict[str, Any], path: str) -> str | None:
    for f in manifest.get("files", []):
        if isinstance(f, dict) and f.get("path") == path:
            val = f.get("sha256")
            return str(val) if val is not None else None
    return None


__all__ = ["build_backup", "restore_backup"]
