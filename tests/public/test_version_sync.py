"""Regression tests: version synchronization (defect 4.13 family).

v0.1 drifted: ``pyproject.toml`` said one version while the package
``__version__``, every pinned container image tag, and the README/index
"current version" prose said another. Corrected contract:

* ``pyproject.toml`` is the single source of truth; the package
  ``__version__`` must equal it;
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


def _project_version() -> str:
    import tomllib

    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


class TestVersionSync:
    """Versions stay synchronized across the project."""

    def test_pyproject_and_package_version_match(self):
        from knovaryn import __version__

        assert __version__ == _project_version(), (
            f"package __version__ {__version__!r} != pyproject {_project_version()!r}; "
            "pyproject.toml is the single source of truth"
        )

    def test_container_image_pins_track_current_release(self):
        version = _project_version()
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
        version = _project_version()
        claim = re.compile(r"[Aa]lpha \(`(\d+\.\d+\.\d+)`\)")
        wrong: list[str] = []
        for rel in ("README.md", "docs/index.md"):
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            for m in claim.finditer(text):
                if m.group(1) != version:
                    wrong.append(f"{rel}: claims alpha `{m.group(1)}`, current is {version}")
        assert not wrong, "\n".join(wrong)
