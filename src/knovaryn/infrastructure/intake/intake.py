"""Safe source intake (spec §8).

Intake sequence: resolve connector → copy to quarantine → stream-hash SHA-256 →
enforce limits → inspect magic bytes/MIME (not extension) → detect encryption/
corruption → reject special files/traversal → run license + privacy pre-scan →
create immutable source artifact → schedule parsing only after preflight passes.
"""

from __future__ import annotations

import asyncio
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...domain import schemas
from ...domain.errors import ArchiveBombError, IntakeError
from ...domain.hashing import ContentHasher
from ...domain.ids import IdGenerator
from ...domain.policies import default_license_status, detect_injection_patterns

# magic-bytes detection (spec §8.2 step 5): don't trust the extension
_MAGIC: list[tuple[bytes, str]] = [
    (b"%PDF-", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),  # docx/pptx/xlsx/epub are zips
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
]
_MAGIC_MAX = 16


def sniff_media_type(name: str, head: bytes) -> tuple[str, bool]:
    """Return (media_type, from_magic). Extension only as fallback."""
    for magic, mtype in _MAGIC:
        if head.startswith(magic):
            return mtype, True
    guessed, _enc = mimetypes.guess_type(name)
    return (guessed or "application/octet-stream"), False


@dataclass
class IntakeResult:
    source: schemas.SourceDocument
    artifact_id: str
    preflight_ok: bool
    warnings: list[str] = field(default_factory=list)
    injection_hits: list[str] = field(default_factory=list)


class IntakeService:
    def __init__(self, *, ids: IdGenerator, store: Any, quarantine_dir: str | Path) -> None:
        self._ids = ids
        self._store = store
        self._quarantine = Path(quarantine_dir)
        self._quarantine.mkdir(parents=True, exist_ok=True)

    async def ingest_bytes(
        self,
        *,
        project_id: str,
        name: str,
        data: bytes,
        source_kind: schemas.SourceKind = schemas.SourceKind.upload,
        locator: str = "",
        declared_license: str | None = None,
        group_key: str | None = None,
        max_file_bytes: int = 200 * 1024 * 1024,
        verify_archive: bool = True,
        background_tasks: set[asyncio.Task] | None = None,
    ) -> IntakeResult:
        warnings: list[str] = []
        if len(data) > max_file_bytes:
            raise IntakeError(f"file exceeds max size ({len(data)} bytes)")
        if len(data) == 0:
            raise IntakeError("empty file")

        head = data[:_MAGIC_MAX]
        media_type, from_magic = sniff_media_type(name, head)
        if not from_magic:
            warnings.append(
                f"media type inferred from extension ({media_type}); magic bytes unrecognized"
            )

        # detect zip-office subkinds
        if media_type == "application/zip":
            media_type = _zip_subtype(name)

        sha256 = ContentHasher.sha256_bytes(data)

        # quarantine copy (immutable, not rendered)
        qpath = self._quarantine / f"{sha256}.blob"
        if not qpath.exists():
            await asyncio.to_thread(qpath.write_bytes, data)

        # license + privacy pre-scan (deterministic)
        license_status = default_license_status(declared_license)
        injection_hits = []
        if (
            media_type in ("text/markdown", "text/plain", "text/html", "text/xml")
            or "text" in media_type
        ):
            try:
                text = data.decode("utf-8", errors="ignore")
                injection_hits = detect_injection_patterns(text)
            except Exception:  # noqa: BLE001
                injection_hits = []

        # store immutable original artifact
        manifest = await self._store.put(
            data,
            media_type=media_type,
            producer={
                "component": "intake",
                "component_version": "1",
                "config_hash": ContentHasher.cfg_hash({"kind": source_kind.value}),
            },
            privacy="restricted",
        )

        source = schemas.SourceDocument(
            id=self._ids.new_handle("src"),
            project_id=project_id,
            original_name=name,
            media_type=media_type,
            byte_size=len(data),
            sha256=sha256,
            source_kind=source_kind,
            source_locator_redacted=locator,
            declared_license=declared_license,
            license_status=license_status,
            intake_status=schemas.IntakeStatus.preflight_ok,
            artifact_id_original=manifest["artifact_id"],
            group_key=group_key,
            metadata={
                "magic_from_ext": from_magic,
                "injection_hits": injection_hits,
                "quarantine_sha": sha256,
            },
        )
        if injection_hits:
            warnings.append(
                "document shows "
                f"{len(injection_hits)} prompt-injection pattern(s); "
                "evidence-only handling enforced"
            )

        # archive verification if it is a zip-based format we trust
        if verify_archive and media_type == "application/zip":
            try:
                await asyncio.to_thread(
                    _validate_zip_safe, data, max_uncompressed_bytes=max_file_bytes
                )
                warnings.append("zip archive structure verified")
            except ArchiveBombError:
                raise
            except IntakeError as exc:
                source.intake_status = schemas.IntakeStatus.preflight_failed
                source.metadata["intake_error"] = exc.message
                raise IntakeError(f"unsafe archive: {exc.message}") from exc

        return IntakeResult(
            source=source,
            artifact_id=manifest["artifact_id"],
            preflight_ok=True,
            warnings=warnings,
            injection_hits=injection_hits,
        )


def _zip_subtype(name: str) -> str:
    lower = name.lower()
    if lower.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if lower.endswith(".pptx"):
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if lower.endswith(".xlsx"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if lower.endswith(".epub"):
        return "application/epub+zip"
    return "application/zip"


def _validate_zip_safe(data: bytes, max_uncompressed_bytes: int) -> None:
    from .archive import validate_zip_archive

    validate_zip_archive(data, max_uncompressed_bytes=max_uncompressed_bytes)
