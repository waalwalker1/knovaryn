"""Release bundles (spec §15.4, §16 / WP I) — integrity-safe and reproducible.

Assemble an accepted dataset version into a self-contained, distributable
bundle: export files (train/validation/test), a dataset manifest, dataset card
metadata, quality report, and license/privacy summaries.

WP I integrity guarantees:
* **I1** the manifest carries a per-file record ``files[]`` (``logical_path``,
  ``size``, ``sha256``, ``media_type``) so every entry can be verified against
  raw bytes.
* **I2 (fixes P0-8)** the zip's own digest is NOT stored inside the archive
  (no self-referential hash). Instead a *detached* ``release.zip.sha256``
  (hexdigest of the zip bytes) is written alongside the bundle.
* **I3** ``to_zip(reproducible=True)`` (the default) produces byte-for-byte
  reproducible archives: fixed zip timestamps (1980-01-01), stable sorted file
  order, normalized line endings, ``sort_keys=True`` JSON, fixed compression.
* **I4** ``content_root_sha256`` is an optional hash over the concatenated
  per-file sha256 digests (distinct from the zip digest) stored in the manifest.

``build_release_bundle`` returns ``(zip_bytes, detached_sha256_bytes)`` so a
caller can persist both. Verify with :mod:`.verify_release`.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from typing import Any

from ...domain.hashing import ContentHasher

# Fixed zip entry timestamp (1980-01-01 00:00:00) so archives are reproducible.
_FIXED_DT = (1980, 1, 1, 0, 0, 0)
_MEDIA_BY_SUFFIX = {
    ".jsonl": "application/jsonl",
    ".json": "application/json",
    ".md": "text/markdown",
}


def _media_type(path: str) -> str:
    for suffix, mt in _MEDIA_BY_SUFFIX.items():
        if path.endswith(suffix):
            return mt
    return "application/octet-stream"


@dataclass
class ReleaseBundle:
    version: str = ""
    project_id: str = ""
    session_note: str = ""
    files: dict[str, bytes] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    reproducible: bool = True
    _zip_bytes: bytes | None = None

    def add_file(self, logical_path: str, data: bytes) -> None:
        if self._zip_bytes is not None:
            raise RuntimeError("cannot add files after the zip has been built")
        self.files[logical_path] = data

    def _write_zip(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # Deterministic order regardless of dict insertion order (I3).
            entries = dict(self.files)
            entries["manifest.json"] = _json_bytes(self.manifest)
            for path in sorted(entries):
                data = entries[path]
                if self.reproducible:
                    data = data.replace(b"\r\n", b"\n")
                info = zipfile.ZipInfo(filename=path, date_time=_FIXED_DT)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                if self.reproducible:
                    info.create_system = 0  # MS-DOS: stable across platforms
                zf.writestr(info, data)
        return buf.getvalue()

    def to_zip(self) -> bytes:
        if self._zip_bytes is None:
            self._zip_bytes = self._write_zip()
        return self._zip_bytes

    def invalidate(self) -> None:
        self._zip_bytes = None

    def sha256(self) -> str:
        return ContentHasher.sha256_bytes(self.to_zip())

    def detached_sha256(self) -> str:
        """I2: hexdigest of the zip bytes, to be written *alongside* the archive
        (``release.zip.sha256``) — never stored inside it (fixes P0-8)."""
        return self.sha256()

    def detached_sha256_bytes(self) -> bytes:
        return self.detached_sha256().encode("ascii") + b"\n"

    def byte_size(self) -> int:
        return len(self.to_zip())


def _json_bytes(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")


def _line_count(data: bytes) -> int:
    text = data.decode("utf-8", errors="replace")
    return len([ln for ln in text.splitlines() if ln.strip()])


def build_release_bundle(
    *,
    version: str,
    project_id: str,
    session_note: str,
    split_files: dict[str, bytes],  # split -> export bytes (train/validation/test)
    dataset_card: dict[str, Any],
    quality_report: dict[str, Any],
    license_summary: dict[str, Any],
    privacy_summary: dict[str, Any],
    source_manifest: dict[str, Any],
    readme: str,
    include_content_root_hash: bool = True,
    reproducible: bool = True,
) -> ReleaseBundle:
    """Build a release bundle (WP I).

    The I2 detached checksum is available as ``bundle.detached_sha256_bytes()``
    (hexdigest of the zip bytes written *alongside* the archive) — it is NEVER
    stored inside the archive, fixing the P0-8 self-referential hash. The
    in-archive manifest carries per-file records + ``content_root_sha256`` (I1,
    I4).
    """
    bundle = ReleaseBundle(
        version=version, project_id=project_id, session_note=session_note, reproducible=reproducible
    )
    for split, data in split_files.items():
        bundle.add_file(f"data/{split}.jsonl", data)
    bundle.add_file("README.md", readme.encode("utf-8"))
    bundle.add_file("dataset_card.json", _json_bytes(dataset_card))
    bundle.add_file("quality_report.json", _json_bytes(quality_report))
    bundle.add_file("license_summary.json", _json_bytes(license_summary))
    bundle.add_file("privacy_summary.json", _json_bytes(privacy_summary))
    bundle.add_file("source_manifest.json", _json_bytes(source_manifest))

    # I1: per-file manifest records (size + sha256 + media_type) computed from
    # the bytes that will actually be zipped.
    file_records = {}
    content = {}
    for path, data in sorted(bundle.files.items()):
        if reproducible:
            data = data.replace(b"\r\n", b"\n")
        digest = ContentHasher.sha256_bytes(data)
        file_records[path] = {
            "logical_path": path,
            "size": len(data),
            "sha256": digest,
            "media_type": _media_type(path),
        }
        content[path] = digest

    # I4: content_root_sha256 distinct from the zip digest (over concatenated
    # per-file digests, ordered). Never equal to the zip's own hash.
    if include_content_root_hash:
        root_digest = ContentHasher.sha256_bytes(
            "".join(content[p] for p in sorted(content)).encode("ascii")
        )
    else:
        root_digest = None

    bundle.manifest = {
        "schema": "knovaryn-release/1.1",
        "version": version,
        "project_id": project_id,
        "session_note": session_note,
        "created_at_note": "see manifest.json for provenance",
        "split_counts": {k: _line_count(v) for k, v in split_files.items()},
        "quality_report_hash": ContentHasher.cfg_hash(quality_report),
        "files": list(file_records.values()),
        "content_root_sha256": root_digest,
        "reproducible": reproducible,
        # I2: NO bundle_sha256 / zip digest here — the manifest must not be
        # self-referential; the detached checksum lives outside the archive.
    }

    bundle.to_zip()  # materialize now so sha256()/byte_size() are stable
    return bundle
