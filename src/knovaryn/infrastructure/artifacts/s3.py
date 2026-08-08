"""S3-compatible artifact storage extra (spec §21.2).

Implemented with ``aioboto3`` when the optional ``s3`` extra is installed.
Graceful degradation: if aioboto3 is unavailable, exposes an explicit
``UnsupportedOperationError`` so the deployment fails loudly, never silently.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from ...domain.errors import CorruptedArtifactError, NotFoundError, UnsupportedOperationError
from ...domain.hashing import ContentHasher


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class S3ArtifactStore:
    """Content-addressed S3-compatible store.

    Blob key: ``objects/<sha>/<sha>``; manifest: ``manifests/<sha>.manifest.json``.
    Commits are atomic: write blob first, then manifest (readers use manifest as
    the commit marker; a blob without a manifest is an incomplete upload).
    """

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        region: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        legal_hold: bool = False,
    ) -> None:
        try:
            import aioboto3  # noqa: F401
        except ImportError as exc:  # pragma: no cover - optional dep
            raise UnsupportedOperationError(
                "S3 artifact store requires the 'knovaryn[s3]' extra (aioboto3). "
                "Install it or switch storage.artifact_backend to 'local'."
            ) from exc
        self.bucket = bucket
        self.endpoint_url = endpoint_url
        self.region = region
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.legal_hold = legal_hold
        self._session_factory = aioboto3.Session()

    def _client(self):
        return self._session_factory.client(
            "s3",
            endpoint_url=self.endpoint_url,
            region_name=self.region,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
        )

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
        blobj = f"objects/{sha256[:2]}/{sha256}"
        manobj = f"manifests/{sha256}.manifest.json"
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
        async with self._client() as s3:
            if not await self._obj_exists(s3, blobj):
                await s3.put_object(Bucket=self.bucket, Key=blobj, Body=data, ContentType=media_type)
            # manifest last = commit marker
            if not await self._obj_exists(s3, manobj):
                await s3.put_object(Bucket=self.bucket, Key=manobj, Body=json.dumps(manifest, sort_keys=True))
            else:
                existing = json.loads((await self._get_obj(s3, manobj)).decode("utf-8"))
                manifest = existing
        return manifest

    async def put_stream(self, producer: dict[str, Any], *, media_type: str, parent: str | None = None):
        raise UnsupportedOperationError("streaming write not yet wired for S3; use put()")

    async def get(self, artifact_id_or_sha: str) -> bytes:
        sha = self._resolve(artifact_id_or_sha)
        blobj = f"objects/{sha[:2]}/{sha}"
        async with self._client() as s3:
            try:
                body = await s3.get_object(Bucket=self.bucket, Key=blobj)
                data = await body["Body"].read()
            except Exception as exc:
                raise NotFoundError(f"artifact {artifact_id_or_sha} not found") from exc
        if hashlib.sha256(data).hexdigest() != sha:
            raise CorruptedArtifactError(f"artifact {artifact_id_or_sha} failed checksum")
        return data

    async def get_meta(self, artifact_id_or_sha: str) -> dict[str, Any]:
        sha = self._resolve(artifact_id_or_sha)
        manobj = f"manifests/{sha}.manifest.json"
        async with self._client() as s3:
            try:
                body = await s3.get_object(Bucket=self.bucket, Key=manobj)
                raw = (await body["Body"].read()).decode("utf-8")
            except Exception as exc:
                raise NotFoundError(f"artifact {artifact_id_or_sha} not found") from exc
        return json.loads(raw)

    async def exists(self, artifact_id_or_sha: str) -> bool:
        try:
            await self.get_meta(artifact_id_or_sha)
            return True
        except (NotFoundError, CorruptedArtifactError):
            return False

    async def delete_object_if_unreferenced(self, sha256: str) -> bool:
        if self.legal_hold:
            return False
        async with self._client() as s3:
            await s3.delete_object(Bucket=self.bucket, Key=f"objects/{sha256[:2]}/{sha256}")
        return True

    async def iter_blobs(self) -> AsyncIterator[str]:
        async with self._client() as s3:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self.bucket, Prefix="objects/"):
                for obj in page.get("Contents", []):
                    yield obj["Key"].rsplit("/", 1)[-1]

    async def _obj_exists(self, s3, key: str) -> bool:
        try:
            await s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    async def _get_obj(self, s3, key: str) -> bytes:
        body = await s3.get_object(Bucket=self.bucket, Key=key)
        return await body["Body"].read()

    def _resolve(self, artifact_id_or_sha: str) -> str:
        if not artifact_id_or_sha.startswith("art_"):
            return artifact_id_or_sha
        raise UnsupportedOperationError(
            "S3 store requires full sha256 handles; art_ short handles are not indexed."
        )
