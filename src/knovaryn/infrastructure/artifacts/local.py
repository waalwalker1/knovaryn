"""Content-addressed artifact storage (spec §6.3, §21.2).

Local filesystem CAS: content-addressed immutable bytes + manifest metadata.
Streaming writes, checksum verification, reference counting hooks for GC.
S3-compatible adapter lives alongside (``s3.py``).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import aiofiles

from ...domain.errors import CorruptedArtifactError, NotFoundError
from ...domain.hashing import ContentHasher

_MANIFEST_SUFFIX = ".manifest.json"


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class LocalArtifactStore:
    """Local content-addressed store.

    Layout::

        <root>/objects/<sha256-prefix2>/<sha256>         # raw bytes
        <root>/manifests/<sha256>.manifest.json          # immutable manifest

    Blob location is derived from sha256 (deduplicated by content).
    """

    def __init__(self, root: str | Path, *, legal_hold: bool = False) -> None:
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.manifests = self.root / "manifests"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.manifests.mkdir(parents=True, exist_ok=True)
        self.legal_hold = legal_hold

    def _blob_path(self, sha256: str) -> Path:
        return self.objects / sha256[:2] / sha256

    def _manifest_path(self, sha256: str) -> Path:
        return self.manifests / f"{sha256}{_MANIFEST_SUFFIX}"

    async def put(
        self,
        data: bytes,
        *,
        media_type: str,
        producer: dict[str, Any],
        parents: list[str] | None = None,
        privacy: str = "restricted",
    ) -> dict[str, Any]:
        sha256 = ContentHasher.sha256_bytes(data)
        blob = self._blob_path(sha256)
        if not blob.exists():
            blob.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(blob, "wb") as fh:
                await fh.write(data)
            # atomic-ish: manifest written after blob
            manifest = {
                "schema_version": "1.0",
                "artifact_id": f"art_{sha256[:16]}",
                "sha256": sha256,
                "media_type": media_type,
                "byte_size": len(data),
                "created_at": utcnow_iso(),
                "producer": producer,
                "parents": parents or [],
                "privacy": privacy,
                "encryption": None,
            }
            async with aiofiles.open(self._manifest_path(sha256), "w", encoding="utf-8") as fh:
                await fh.write(json.dumps(manifest, sort_keys=True))
        else:
            manifest = await self.get_meta(sha256)
        return manifest

    async def put_stream(
        self, producer: dict[str, Any], *, media_type: str, parent: str | None = None
    ) -> Any:
        class _Writer:
            def __init__(
                self, store: LocalArtifactStore, producer: dict[str, Any], media_type: str
            ) -> None:
                self._store = store
                self._producer = producer
                self._media_type = media_type
                self._chunks: list[bytes] = []
                self._h = hashlib.sha256()

            async def write(self, data: bytes) -> None:
                self._chunks.append(data)
                self._h.update(data)

            async def commit(self) -> dict[str, Any]:
                payload = b"".join(self._chunks)
                sha = self._h.hexdigest()
                blob = self._store._blob_path(sha)
                if not blob.exists():
                    blob.parent.mkdir(parents=True, exist_ok=True)
                    async with aiofiles.open(blob, "wb") as fh:
                        await fh.write(payload)
                manifest = {
                    "schema_version": "1.0",
                    "artifact_id": f"art_{sha[:16]}",
                    "sha256": sha,
                    "media_type": self._media_type,
                    "byte_size": len(payload),
                    "created_at": utcnow_iso(),
                    "producer": self._producer,
                    "parents": [parent] if parent else [],
                    "privacy": "restricted",
                    "encryption": None,
                }
                async with aiofiles.open(
                    self._store._manifest_path(sha), "w", encoding="utf-8"
                ) as fh:
                    await fh.write(json.dumps(manifest, sort_keys=True))
                return manifest

        return _Writer(self, producer, media_type)

    async def get(self, artifact_id_or_sha: str) -> bytes:
        sha = _resolve(self, artifact_id_or_sha)
        blob = self._blob_path(sha)
        if not blob.exists():
            raise NotFoundError(f"artifact {artifact_id_or_sha} not found")
        async with aiofiles.open(blob, "rb") as fh:
            data = await fh.read()
        if hashlib.sha256(data).hexdigest() != sha:
            raise CorruptedArtifactError(f"artifact {artifact_id_or_sha} failed checksum")
        return cast(bytes, data)

    async def get_meta(self, artifact_id_or_sha: str) -> dict[str, Any]:
        sha = _resolve(self, artifact_id_or_sha)
        mpath = self._manifest_path(sha)
        if not mpath.exists():
            # derive minimal manifest from bytes if manifest missing (orphan repair)
            blob = self._blob_path(sha)
            if not blob.exists():
                raise NotFoundError(f"artifact {artifact_id_or_sha} not found")
            async with aiofiles.open(blob, "rb") as fh:
                data = await fh.read()
            return {
                "artifact_id": f"art_{sha[:16]}",
                "sha256": sha,
                "media_type": "application/octet-stream",
                "byte_size": len(data),
                "created_at": utcnow_iso(),
                "producer": {"component": "repair(orphan)"},
                "parents": [],
                "privacy": "restricted",
                "encryption": None,
            }
        async with aiofiles.open(mpath, encoding="utf-8") as fh:
            return cast(dict[str, Any], json.loads(await fh.read()))

    async def exists(self, artifact_id_or_sha: str) -> bool:
        try:
            await self.get_meta(artifact_id_or_sha)
            return True
        except (NotFoundError, CorruptedArtifactError):
            return False

    async def delete_object_if_unreferenced(self, sha256: str) -> bool:
        """Drop a blob only when not under legal hold (reference GC is caller's job)."""
        if self.legal_hold:
            return False
        blob = self._blob_path(sha256)
        if blob.exists():
            blob.unlink()
            return True
        return False

    async def iter_blobs(self) -> AsyncIterator[str]:
        if not self.objects.exists():
            return
        for p in self.objects.rglob("*"):
            if p.is_file():
                yield p.name


def _resolve(store: LocalArtifactStore, artifact_id_or_sha: str) -> str:
    """Support both ``art_<sha16>`` handles and full sha256."""
    if artifact_id_or_sha.startswith("art_"):
        # For deterministic local content we store manifest keyed by sha256; to
        # resolve an art_ handle we scan manifests. This is O(n); acceptable for
        # local small stores and can be indexed later. Prefer passing sha256.
        for m in store.manifests.glob(f"*{_MANIFEST_SUFFIX}"):
            try:
                import json as _json

                with open(m, encoding="utf-8") as fh:
                    data = _json.load(fh)
                if data.get("artifact_id") == artifact_id_or_sha:
                    return cast(str, data["sha256"])
            except Exception:
                continue
        raise NotFoundError(f"artifact {artifact_id_or_sha} not found")
    return artifact_id_or_sha
