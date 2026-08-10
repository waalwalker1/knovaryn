"""Adversarial intake safety (spec §8, exec rule: safe source intake).

Verify that malicious inputs — zip bombs, member path traversal, malformed
archives, sneaky media types — are rejected with typed errors before any
downstream rendering.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from knovaryn.domain.errors import (
    ArchiveBombError,
    IntakeError,
    PathTraversalError,
)
from knovaryn.infrastructure.intake.archive import validate_zip_archive
from knovaryn.infrastructure.intake.intake import sniff_media_type
from knovaryn.infrastructure.intake.paths import validate_local_path


def _zip_bytes(entries: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return buf.getvalue()


def test_rejects_member_path_traversal() -> None:
    data = _zip_bytes([("../../etc/passwd", b"root:x:0:0:")])
    with pytest.raises(IntakeError):
        validate_zip_archive(data, max_uncompressed_bytes=10_000)


def test_rejects_absolute_path_member() -> None:
    data = _zip_bytes([("/etc/passwd", b"root:x:0:0:")])
    with pytest.raises(IntakeError):
        validate_zip_archive(data, max_uncompressed_bytes=10_000)


def test_rejects_zip_bomb_ratio() -> None:
    # highly-compressible repeated payload => high compression ratio
    payload = b"A" * (20 * 1024 * 1024)  # 20 MiB of 'A' compresses to ~20 KiB
    data = _zip_bytes([("bomb.txt", payload)])
    with pytest.raises(ArchiveBombError):
        validate_zip_archive(data, max_uncompressed_bytes=100 * 1024 * 1024)


def test_rejects_archive_over_total_limit() -> None:
    payload = b"B" * (64 * 1024)  # 64 KiB, compresses small
    data = _zip_bytes([("a.txt", payload), ("b.txt", payload)])
    with pytest.raises(ArchiveBombError):
        validate_zip_archive(data, max_uncompressed_bytes=32 * 1024)


def test_rejects_malformed_zip() -> None:
    with pytest.raises(IntakeError):
        validate_zip_archive(b"this is definitely not a zip archive", max_uncompressed_bytes=10_000)


def test_magic_bytes_override_extension() -> None:
    # a file named .pdf but with zip magic must be classified as zip
    head = b"PK\x03\x04" + b"\x00" * 16
    mtype, from_magic = sniff_media_type("report.pdf", head)
    assert from_magic is True
    assert mtype == "application/zip"


def test_magic_bytes_pdf() -> None:
    mtype, from_magic = sniff_media_type("whatever.txt", b"%PDF-1.7" + b"\x00" * 16)
    assert from_magic is True
    assert mtype == "application/pdf"


def test_path_traversal_rejected(tmp_path) -> None:  # noqa: ANN001
    root = str(tmp_path / "safe")
    with pytest.raises(PathTraversalError):
        validate_local_path("../etc/passwd", allowed_roots=[root])


def test_absolute_path_outside_root_rejected(tmp_path) -> None:  # noqa: ANN001
    root = str(tmp_path / "safe")
    outside = tmp_path / "other" / "file.txt"
    with pytest.raises(PathTraversalError):
        validate_local_path(str(outside), allowed_roots=[root])


def test_safe_path_within_root_accepted(tmp_path) -> None:  # noqa: ANN001
    safe_dir = tmp_path / "safe"
    safe_dir.mkdir(parents=True, exist_ok=True)
    target = safe_dir / "doc.md"
    target.touch()
    resolved = validate_local_path(str(target), allowed_roots=[str(safe_dir)])
    assert resolved == target
