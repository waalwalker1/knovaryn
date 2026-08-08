"""Release bundles (spec §15.4, §16).

Assemble an accepted dataset version into a self-contained, distributable
bundle: export files (train/validation/test), a dataset manifest, dataset card
metadata, quality report, and license/privacy summaries. The bundle is content-
addressed (zip hash) and immutable.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from typing import Any

from ...domain.hashing import ContentHasher


@dataclass
class ReleaseBundle:
    version: str = ""
    project_id: str = ""
    session_note: str = ""
    files: dict[str, bytes] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    _zip_bytes: bytes = b""

    def add_file(self, logical_path: str, data: bytes) -> None:
        self.files[logical_path] = data

    def to_zip(self) -> bytes:
        if self._zip_bytes:
            return self._zip_bytes
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for path, data in sorted(self.files.items()):
                zf.writestr(path, data)
            zf.writestr("manifest.json", json.dumps(self.manifest, indent=2, sort_keys=True))
        self._zip_bytes = buf.getvalue()
        return self._zip_bytes

    def sha256(self) -> str:
        return ContentHasher.sha256_bytes(self.to_zip())

    def byte_size(self) -> int:
        return len(self.to_zip())


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
) -> ReleaseBundle:
    bundle = ReleaseBundle(version=version, project_id=project_id, session_note=session_note)
    for split, data in split_files.items():
        bundle.add_file(f"data/{split}.jsonl", data)
    bundle.add_file("README.md", readme.encode("utf-8"))
    bundle.add_file("dataset_card.json", _json_bytes(dataset_card))
    bundle.add_file("quality_report.json", _json_bytes(quality_report))
    bundle.add_file("license_summary.json", _json_bytes(license_summary))
    bundle.add_file("privacy_summary.json", _json_bytes(privacy_summary))
    bundle.add_file("source_manifest.json", _json_bytes(source_manifest))

    bundle.manifest = {
        "schema": "knovaryn-release/1.0",
        "version": version,
        "project_id": project_id,
        "session_note": session_note,
        "created_at_note": "see manifest.json for provenance",
        "split_counts": {k: _line_count(v) for k, v in split_files.items()},
        "quality_report_hash": ContentHasher.cfg_hash(quality_report),
        "bundle_sha256": "",  # filled below
    }
    # content hash of zip (computed without the final hash to avoid self-reference)
    digest = ContentHasher.sha256_bytes(bundle.to_zip())
    bundle.manifest["bundle_sha256"] = digest
    # `self.manifest` now carries the completed manifest; to_zip() writes it under
    # manifest.json. Do NOT also add it to `self.files`, or the zip would contain
    # two manifest.json entries.
    bundle._zip_bytes = b""  # invalidate cached zip
    return bundle


def _json_bytes(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")


def _line_count(data: bytes) -> int:
    text = data.decode("utf-8", errors="replace")
    return len([ln for ln in text.splitlines() if ln.strip()])
