"""Archive and office safety (spec §8.5).

Protect against zip bombs (compressed vs uncompressed ratio/size limits),
reject absolute paths and ``..`` traversal in members, and raise typed errors
for corrupted archives. Never extract to disk inside the application; members
are streamed and length-checked.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import AsyncIterator
from pathlib import PurePosixPath

from ...domain.errors import ArchiveBombError, IntakeError

_SAFE_SUFFIXES = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".html",
    ".htm",
    ".md",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
    ".csv",
    ".json",
    ".epub",
    ".xml",
}

_MAX_MEMBERS = 2000
_MAX_COMPRESSED_RATIO = 200.0

# nested-archive policy (spec §8.5 / WP G4): archive members that are themselves
# archives are rejected unless explicitly allowed (they hide decompression bombs
# behind nested zip layers and are never parseable in our single-pass model).
_NESTED_ARCHIVE_SUFFIXES = {
    ".zip",
    ".tar",
    ".tgz",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
}


def validate_zip_archive(
    data: bytes,
    *,
    max_uncompressed_bytes: int,
    allow_nested: bool = False,
) -> dict[str, object]:
    """Validate a zip for bombs/traversal. Returns member manifest.

    Reads the zip central directory; verifies member names are safe and total
    uncompressed size is within bounds. Raises ArchiveBombError / IntakeError.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise IntakeError("malformed zip archive") from exc

    infos = zf.infolist()
    if len(infos) > _MAX_MEMBERS:
        raise ArchiveBombError("archive has too many members")

    members: dict[str, object] = {}
    total_uncompressed = 0
    for info in infos:
        # traversal / absolute path check
        name = info.filename
        if name.startswith(("/", "\\")):
            raise IntakeError(f"archive member has absolute path: {name!r}")
        parts = PurePosixPath(name.replace("\\", "/")).parts
        if any(p == ".." for p in parts):
            raise IntakeError(f"archive member path traversal: {name!r}")
        # nested-archive check (WP G4) unless explicitly allowed
        if not allow_nested and not info.is_dir():
            member_suffix = PurePosixPath(name).suffix.lower()
            if member_suffix in _NESTED_ARCHIVE_SUFFIXES:
                raise IntakeError(f"nested archive member not allowed: {name!r}")
        # compression ratio bomb check
        if info.file_size > 0 and info.compress_size > 0:
            ratio = info.file_size / info.compress_size
            if ratio > _MAX_COMPRESSED_RATIO:
                raise ArchiveBombError(f"archive member {name!r} has suspicious compression ratio")
        total_uncompressed += info.file_size
        if total_uncompressed > max_uncompressed_bytes:
            raise ArchiveBombError("archive total uncompressed size exceeds limit")
        members[name] = {
            "size": info.file_size,
            "compress_size": info.compress_size,
            "is_dir": info.is_dir(),
        }
    zf.close()
    return members


async def iter_supported_members(data: bytes) -> AsyncIterator[tuple[str, bytes]]:
    """Yield (safe_name, bytes) for archive members we can actually parse."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise IntakeError("malformed zip archive") from exc
    for info in zf.infolist():
        if info.is_dir():
            continue
        suffix = PurePosixPath(info.filename).suffix.lower()
        if suffix not in _SAFE_SUFFIXES:
            continue
        try:
            raw = zf.read(info)
        except (RuntimeError, zipfile.BadZipFile, NotImplementedError):
            continue  # skip encrypted/corrupt members
        yield info.filename, raw
    zf.close()
