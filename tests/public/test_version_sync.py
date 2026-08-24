"""Regression tests: version synchronization (defect 4.13 family).

v0.1 drifted: ``pyproject.toml`` said one version while the package
``__version__``, every pinned container image tag, and the README/index
"current version" prose said another. Corrected contract:

* ``src/knovaryn/__init__.py::__version__`` is the single authoritative
  literal; ``pyproject.toml`` carries NO version of its own — it declares
  ``dynamic = ["version"]`` and hatchling consumes the literal at build
  time, so build metadata cannot drift from the package;
* every pinned ``ghcr.io/knovaryn/knovaryn:<tag>`` reference under deploy/
  must pin exactly the current version (pinning exists so a release is
  reproducible — a stale pin deploys the WRONG release);
* user-facing "current version" claims in README/docs index must not name a
  different version than the package.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.unit


def _authoritative_version() -> str:
    """Read the single authoritative version literal (defect 3.5)."""
    init_py = REPO_ROOT / "src" / "knovaryn" / "__init__.py"
    m = re.search(
        r'^__version__\s*=\s*"(\d+\.\d+\.\d+)"',
        init_py.read_text(encoding="utf-8"),
        re.M,
    )
    assert m, f"no __version__ literal in {init_py.relative_to(REPO_ROOT)}"
    return m.group(1)


class TestVersionSync:
    """Versions stay synchronized across the project."""

    def test_pyproject_consumes_authoritative_version(self):
        """pyproject must NOT carry its own version literal: builds take the
        version from the package ``__version__`` via the hatchling hook, so
        wheel/sdist metadata cannot disagree with the installed package."""
        py = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert re.search(r'^dynamic\s*=\s*\[[^\]]*"version"[^\]]*\]', py, re.M), (
            'pyproject [project] must declare dynamic = ["version"] (no version literal of its own)'
        )
        assert re.search(
            r"\[tool\.hatch\.version\][^\[]*path\s*=\s*\"src/knovaryn/__init__\.py\"",
            py,
            re.S,
        ), "[tool.hatch.version] must point at src/knovaryn/__init__.py"

    def test_package_exports_the_authoritative_version(self):
        from knovaryn import __version__

        assert __version__ == _authoritative_version()

    def test_container_image_pins_track_current_release(self):
        version = _authoritative_version()
        pattern = re.compile(r"ghcr\.io/knovaryn/knovaryn:(\S+)")
        stale: list[str] = []
        for path in sorted(REPO_ROOT.glob("deploy/**/*")):
            if not path.is_file():
                continue
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                for m in pattern.finditer(line):
                    if m.group(1) != version:
                        stale.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {m.group(0)}")
        assert not stale, (
            f"pinned image tags do not match current release v{version}:\n" + "\n".join(stale)
        )

    def test_user_facing_current_version_claims_match(self):
        """README / docs index must not claim a different CURRENT version.

        Historical references ("partial in 0.1.0", example dataset semantic
        versions) are fine — only 'this is an alpha (X)' style claims of the
        current release are checked.
        """
        version = _authoritative_version()
        claim = re.compile(r"[Aa]lpha \(`(\d+\.\d+\.\d+)`\)")
        wrong: list[str] = []
        for rel in ("README.md", "docs/index.md"):
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            for m in claim.finditer(text):
                if m.group(1) != version:
                    wrong.append(f"{rel}: claims alpha `{m.group(1)}`, current is {version}")
        assert not wrong, "\n".join(wrong)
