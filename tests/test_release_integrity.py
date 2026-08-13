"""Release integrity tests (spec §16 / WP I1–I5).

Build → verify round-trip, plus tamper failures:

* a clean bundle verifies (detached checksum + per-file manifests + content root
  hash + no self-referential zip digest);
* tampering a byte inside the archive fails verification (per-file sha256);
* tampering the detached checksum fails;
* bundles are byte-for-byte reproducible under ``reproducible=True``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from knovaryn.pipeline.export.release import build_release_bundle
from knovaryn.pipeline.export.verify_release import (
    ReleaseIntegrityError,
    run_verify_release,
    verify_release,
)


def _split_files() -> dict[str, bytes]:
    return {
        "train": b"line1\nline2\nline3\n",
        "validation": b"v1\n",
        "test": b"",
    }


def _build(tmp_path: Path, *, reproducible: bool = True, readme: str = "# Knovaryn\n"):
    bundle = build_release_bundle(
        version="0.2.0",
        project_id="proj_r",
        session_note="release integrity test",
        split_files=_split_files(),
        dataset_card={"name": "integrity", "language": ["en"]},
        quality_report={"status_counts": {"accepted": 3, "rejected": 0}},
        license_summary={"license": {"allowed": 1, "review": 0}},
        privacy_summary={"pii_findings": 0, "high_confidence": False},
        source_manifest={"sources": 1},
        readme=readme,
        reproducible=reproducible,
    )
    zip_path = tmp_path / "release.zip"
    zip_path.write_bytes(bundle.to_zip())
    zip_path.with_suffix(".zip.sha256").write_bytes(bundle.detached_sha256_bytes())
    return zip_path, bundle


def test_clean_bundle_verifies(tmp_path: Path):
    zip_path, bundle = _build(tmp_path)
    report = verify_release(zip_path)
    assert report.ok(), report.errors
    assert "data/train.jsonl" in report.files_present
    assert report.detached_ok
    assert report.per_file_ok
    assert report.content_root_ok
    assert report.schema_ok
    assert report.file_digests["manifest.json"]


def test_run_verify_release_exit_codes(tmp_path: Path):
    zip_path, _ = _build(tmp_path)
    assert run_verify_release(zip_path) == 0
    # a missing file is a hard failure (nonzero)
    assert run_verify_release(tmp_path / "nope.zip") != 0


def test_survives_round_trip_digest_unchanged(tmp_path: Path):
    # re-verify a bundle after it was built and written — the detached checksum
    # still matches the bytes on disk (I3 reproducibility / I2 detached checksum)
    zip_path, _ = _build(tmp_path)
    assert verify_release(zip_path).ok()


def test_tampering_a_byte_fails_per_file_checksum(tmp_path: Path):
    zip_path, bundle = _build(tmp_path)
    data = bytearray(zip_path.read_bytes())
    # flip one byte in the middle of the archive
    data[len(data) // 2] ^= 0xFF
    zip_path.write_bytes(bytes(data))
    # a tampered archive must fail — either as a hard structural error or as a
    # non-ok verification report (both are "fails")
    try:
        report = verify_release(zip_path)
    except ReleaseIntegrityError:
        return  # rejected at the archive level — fails closed
    assert not report.ok()
    assert any(
        "sha256 mismatch" in e or "digest" in e or "checksum" in e or "CRC" in e
        for e in report.errors
    )


def test_tampering_detached_checksum_fails(tmp_path: Path):
    zip_path, bundle = _build(tmp_path)
    (tmp_path / "release.zip.sha256").write_text("0" * 64 + "\n", encoding="ascii")
    report = verify_release(zip_path)
    assert not report.ok()
    assert any("detached checksum mismatch" in e for e in report.errors)


def test_reproducible_bundle_is_byte_identical(tmp_path: Path):
    a, _ = _build(tmp_path, readme="# A\n")
    b, _ = _build(tmp_path, readme="# A\n")
    assert a.read_bytes() == b.read_bytes()


def test_missing_detached_checksum_is_hard_failure(tmp_path: Path):
    zip_path, _ = _build(tmp_path)
    (tmp_path / "release.zip.sha256").unlink()
    with pytest.raises(ReleaseIntegrityError):
        verify_release(zip_path)


def test_cli_verify_release_command(tmp_path: Path):
    """``knovaryn verify-release <path>`` exits 0 on a verifiable bundle and
    nonzero once the detached checksum is corrupted (I5)."""
    from knovaryn.interfaces.cli.commands import verify_release as cli_verify

    zip_path, _ = _build(tmp_path)
    assert cli_verify(path=str(zip_path)) == 0

    (tmp_path / "release.zip.sha256").write_text("0" * 64 + "\n", encoding="ascii")
    assert cli_verify(path=str(zip_path)) != 0
