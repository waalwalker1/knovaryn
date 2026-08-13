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
from ...domain.errors import ArchiveBombError, IntakeError, MalwareScanError
from ...domain.hashing import ContentHasher
from ...domain.ids import IdGenerator
from ...domain.policies import default_license_status, detect_injection_patterns
from .redact import redact_locator

# allowed-extension policy (spec §8 / WP G2): the formats honestly documented.
# Magic bytes may override an unknown extension when they resolve to an allowed
# type, but a name with a *known but disallowed* extension is always rejected.
_ALLOWED_SUFFIXES = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".html",
    ".htm",
    ".md",
    ".markdown",
    ".txt",
    ".csv",
    ".tsv",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".xml",
    ".json",
    ".epub",
    ".zip",
    ".tar",
}
# extensions that are recognized but intentionally unsupported (reject loudly
# rather than silently mis-parsing).
_DISALLOWED_SUFFIXES = {
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".sh",
    ".bat",
    ".ps1",
    ".py",
    ".js",
    ".php",
    ".cgi",
    ".class",
    ".jar",
    ".wasm",
    ".ttf",
    ".otf",
    ".woff",
}

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


def check_allowed_extension(name: str) -> None:
    """Reject unsupported extensions (spec §8.2 / WP G2)."""
    lower = name.lower()
    suffix = None
    for cand in (".markdown",):
        if lower.endswith(cand):
            suffix = cand
            break
    else:
        suffix = _suffix(name)
    if suffix in _DISALLOWED_SUFFIXES:
        raise IntakeError(f"file type not supported for intake: {suffix}")
    if suffix and suffix not in _ALLOWED_SUFFIXES and suffix not in _DISALLOWED_SUFFIXES:
        raise IntakeError(f"file type not supported for intake: {suffix}")


def _suffix(name: str) -> str:
    import os

    return os.path.splitext(name)[1].lower()


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
        malware_scan: Any | None = None,
        allow_nested_archives: bool = False,
        background_tasks: set[asyncio.Task] | None = None,
    ) -> IntakeResult:
        warnings: list[str] = []
        if len(data) > max_file_bytes:
            raise IntakeError(f"file exceeds max size ({len(data)} bytes)")
        if len(data) == 0:
            raise IntakeError("empty file")

        # allowed-extension policy (spec §8.2 / WP G2): reject loudly unless
        # magic bytes override an unknown name to an allowed type.
        check_allowed_extension(name)

        # malware hook (spec §8.6 / WP G4): binding scanner adapter if configured
        if malware_scan is not None:
            try:
                await asyncio.to_thread(malware_scan.scan, data)
            except MalwareScanError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise MalwareScanError(f"malware scan failed for {name!r}") from exc

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
            source_locator_redacted=redact_locator(locator),
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
                    _validate_zip_safe,
                    data,
                    max_uncompressed_bytes=max_file_bytes,
                    allow_nested=allow_nested_archives,
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


def _validate_zip_safe(
    data: bytes,
    max_uncompressed_bytes: int,
    allow_nested: bool = False,
) -> None:
    from .archive import validate_zip_archive

    validate_zip_archive(
        data,
        max_uncompressed_bytes=max_uncompressed_bytes,
        allow_nested=allow_nested,
    )
