"""Defect 3.5 (v0.2.1) — every public version surface must be synchronized.

``knovaryn.__version__`` is the single authoritative source; the checker in
``scripts/check_version_sync.py`` verifies pyproject, CITATION.cff,
codemeta.json, REST/OpenAPI metadata, MCP server metadata, container labels,
the docs home config, and the README current-version marker all match.
Historical changelog entries are exempt (contract §3.5).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "scripts" / "check_version_sync.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_version_sync", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_version_sync"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_all_public_version_surfaces_match_authoritative_version() -> None:
    checker = _load_checker()
    version = checker.authoritative_version()
    assert version, "knovaryn.__init__ must declare __version__"

    errors = checker.check(allow_drift=False)
    assert not errors, f"public version surfaces drifted from {version}:\n- " + "\n- ".join(
        e.split("\n  fix:")[0] for e in errors
    )


def test_authoritative_version_is_semver() -> None:
    checker = _load_checker()
    version = checker.authoritative_version()
    parts = version.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts), (
        f"authoritative version {version!r} is not X.Y.Z"
    )
