"""Regression tests: no legacy branding in public surfaces.

The product was renamed to Knovaryn from an earlier umbrella brand, and
``src/knovaryn/identity.py`` declares the legacy spellings as rejected
identifiers — yet v0.1 still shipped them in the PUBLIC docs: the mkdocs nav,
the docs index link, an entire page slug (``omnitrain-mcp.md``), and
marketing prose. Corrected contract: the legacy brand appears ONLY inside the
enforcement code that defines it as rejected (identity.py and its tests) —
nowhere else in the tracked tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.unit

LEGACY_SPELLINGS = ("OmniTrain", "omnitrain", "OMNITRAIN")

# Enforcement code DEFINES the legacy identifiers in order to reject them;
# it is the one place they are allowed to appear.
ALLOWED_ENFORCEMENT_FILES = {
    Path("src/knovaryn/identity.py"),
    Path("tests/test_identity.py"),
    Path("tests/public/test_no_omnitrain_branding.py"),
}

TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".html",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".cfg",
    ".ini",
    ".txt",
    ".css",
    ".js",
    ".xml",
}


def _tracked_text_files() -> list[Path]:
    """Every tracked text file, using git (respects exclude/ignore rules)."""
    import subprocess

    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    files = []
    for line in out.stdout.splitlines():
        p = Path(line)
        if p.suffix.lower() in TEXT_SUFFIXES:
            files.append(p)
    return files


class TestNoOmnitrainBranding:
    """No legacy branding in public surfaces."""

    def test_no_legacy_brand_in_docs_or_config(self):
        """Zero legacy spellings anywhere outside enforcement code."""
        leaks: list[str] = []
        for rel in _tracked_text_files():
            if rel in ALLOWED_ENFORCEMENT_FILES:
                continue
            text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                for spelling in LEGACY_SPELLINGS:
                    if spelling in line:
                        leaks.append(f"{rel}:{lineno}: {spelling!r}")
        assert not leaks, "legacy brand strings found outside enforcement code:\n" + "\n".join(
            leaks
        )

    def test_no_legacy_page_slug(self):
        """No tracked file name carries the legacy brand."""
        bad = [
            str(f)
            for f in _tracked_text_files()
            if f not in ALLOWED_ENFORCEMENT_FILES and "omnitrain" in str(f).lower()
        ]
        assert not bad, f"legacy-branded file names: {bad}"

    def test_package_metadata_is_clean(self):
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        for spelling in LEGACY_SPELLINGS:
            assert spelling not in pyproject
