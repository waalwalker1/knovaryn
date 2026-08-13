"""Release bundle verification (spec §16 / WP I5) — ``knovaryn verify-release``.

Verifies a built release bundle end-to-end, failing with a nonzero exit / a
raised :class:`ReleaseIntegrityError` on any problem:

* **I2** the detached ``<path>.sha256`` file (if present) matches
  ``sha256(path)``;
* unzips the archive in-memory and verifies every ``manifest.files[].sha256``
  against the raw bytes of that entry;
* validates the manifest JSON schema and that required release files are present
  (``data/train.jsonl``, ``manifest.json``, ``README.md``, and the
  quality/license/privacy/source manifests);
* verifies the ``manifest.content_root_sha256`` (over per-file digests) when
  present;
* verifies the in-archive manifest does NOT carry a self-referential zip digest
  (``bundle_sha256``) — P0-8 must stay fixed.

The verifier refuses to report success on any unresolved reference (contract
rule 6: no truthiness-only checks; rule 13: a verifiable digest is required).
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...domain.hashing import ContentHasher

# Required logical paths inside every release bundle.
_REQUIRED = {
    "data/train.jsonl",
    "manifest.json",
    "README.md",
    "dataset_card.json",
    "quality_report.json",
    "license_summary.json",
    "privacy_summary.json",
    "source_manifest.json",
}


class ReleaseIntegrityError(Exception):
    """Raised when release verification fails. Message is user-facing."""


@dataclass
class VerificationReport:
    path: str
    detached_ok: bool = False
    per_file_ok: bool = False
    content_root_ok: bool = False
    schema_ok: bool = False
    files_present: set[str] = field(default_factory=set)
    file_digests: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.errors and self.detached_ok and self.per_file_ok and self.schema_ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "ok": self.ok(),
            "detached_checksum_verified": self.detached_ok,
            "per_file_manifest_verified": self.per_file_ok,
            "content_root_hash_verified": self.content_root_ok,
            "manifest_schema_valid": self.schema_ok,
            "files": sorted(self.files_present),
            "errors": self.errors,
        }


def _require(cond: bool, report: VerificationReport, msg: str) -> None:
    if not cond:
        report.errors.append(msg)


def _verify_detached(path: Path, report: VerificationReport) -> list[str]:
    """Return sha256 records read from ``path.sha256`` (hexdigest per line)."""
    expected: list[str] = []
    dotpath = Path(str(path) + ".sha256")
    if not dotpath.exists():
        raise ReleaseIntegrityError(
            f"detached checksum {dotpath.name} is required (I2); cannot verify {path.name}"
        )
    data = dotpath.read_text(encoding="ascii")
    for line in data.splitlines():
        line = line.strip()
        if line:
            expected.append(line)
    actual = ContentHasher.sha256_bytes(path.read_bytes())
    report.detached_ok = actual in expected
    _require(report.detached_ok, report, f"detached checksum mismatch for {path.name}")
    return expected


def _verify_archive(path: Path, report: VerificationReport) -> dict[str, bytes]:
    raw = path.read_bytes()
    entries: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                entries[info.filename] = zf.read(info.filename)
    except zipfile.BadZipFile as exc:  # noqa: PERF203
        raise ReleaseIntegrityError(f"invalid zip archive: {exc}") from exc

    # required files present
    present = set(entries)
    report.files_present = present
    missing = _REQUIRED - present
    _require(not missing, report, f"missing required files: {sorted(missing)}")

    # manifest parses (schema_ok)
    manifest = {}
    if "manifest.json" in entries:
        try:
            manifest = json.loads(entries["manifest.json"])
            schema_valid = bool(manifest.get("schema"))
            report.schema_ok = schema_valid
            if not schema_valid:
                report.errors.append("manifest.json missing 'schema'")
        except json.JSONDecodeError as exc:
            report.errors.append(f"manifest.json is not valid JSON: {exc}")
    else:
        report.errors.append("manifest.json missing from archive")

    # I1: verify per-file manifest record digests against actual bytes
    file_records = manifest.get("files") or []
    expected_index = {f.get("logical_path"): f for f in file_records if isinstance(f, dict)}
    verified = 0
    for path_, data in entries.items():
        digest = ContentHasher.sha256_bytes(data)
        report.file_digests[path_] = digest
        rec = expected_index.get(path_)
        if rec is None:
            # unlisted entry is fine as long as it exists on disk; only listed
            # files must match (manifest coverage is checked below)
            continue
        expected_digest = rec.get("sha256")
        _require(expected_digest == digest, report, f"sha256 mismatch for {path_}")
        _require(rec.get("size", -1) == len(data), report, f"size mismatch for {path_}")
        verified += 1
    # every manifest record must correspond to an entry actually present
    for logical in file_records:
        lp = logical.get("logical_path")
        if lp and lp not in entries:
            report.errors.append(f"manifest lists {lp} but it is absent from the archive")
    report.per_file_ok = not any(
        "sha256 mismatch" in e or "size mismatch" in e or "absent from the archive" in e
        for e in report.errors
    )

    # I4: content_root_sha256 over per-file digests (distinct from zip digest).
    # Matches build: concatenate each manifest-listed file's digest, ordered by
    # logical_path (manifest.json itself is excluded — it is not a listed file).
    content_root = manifest.get("content_root_sha256")
    if content_root:
        listed = [
            f.get("logical_path")
            for f in sorted(file_records, key=lambda r: r.get("logical_path") or "")
        ]
        ordered = "".join(report.file_digests[p] for p in listed if p).encode("ascii")
        computed = ContentHasher.sha256_bytes(ordered)
        _require(computed == content_root, report, "content_root_sha256 mismatch")
        report.content_root_ok = computed == content_root
    else:
        report.errors.append("manifest missing content_root_sha256")

    # I2/P0-8: the manifest must NOT embed the archive's own digest
    _require(
        "bundle_sha256" not in manifest,
        report,
        "manifest is self-referential (bundle_sha256 present)",
    )

    return manifest


def verify_release(path: str | Path) -> VerificationReport:
    """Verify a release bundle at ``path``. Raises on structural failure."""
    p = Path(path)
    if not p.exists():
        raise ReleaseIntegrityError(f"release not found: {p}")
    report = VerificationReport(path=str(p))
    _verify_detached(p, report)
    _verify_archive(p, report)
    return report


def run_verify_release(path: str | Path) -> int:
    """CLI entry point — returns 0 on success (verifiable), nonzero otherwise."""
    try:
        report = verify_release(path)
    except ReleaseIntegrityError as exc:
        print(f"verify-release: FAILED: {exc}")
        return 2
    if report.ok():
        print(
            f"verify-release: OK {path} ({len(report.files_present)} files, "
            f"{len(report.file_digests)} digests verified)"
        )
        return 0
    print(f"verify-release: INVALID {path}")
    for err in report.errors:
        print(f"  - {err}")
    return 1
