"""Artifact store factory (spec §21.2)."""

from __future__ import annotations

from typing import Any

from ...domain.errors import ConfigurationError
from .local import LocalArtifactStore
from .s3 import S3ArtifactStore


def build_artifact_store(
    *,
    backend: str,
    config: dict[str, Any],
) -> Any:
    if backend == "local":
        root = config.get("artifact_root", "./.knovaryn/artifacts")
        return LocalArtifactStore(root, legal_hold=bool(config.get("legal_hold", False)))
    if backend in ("s3", "s3-compatible", "minio"):
        return S3ArtifactStore(
            bucket=config["bucket"],
            endpoint_url=config.get("endpoint_url"),
            region=config.get("region"),
            access_key_id=config.get("access_key_id"),
            secret_access_key=config.get("secret_access_key"),
            legal_hold=bool(config.get("legal_hold", False)),
        )
    raise ConfigurationError(f"unknown artifact_backend: {backend!r}")
