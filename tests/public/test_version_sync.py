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

v0.2.2 contract §4.3 extended coherence (TestReleaseMetadataCoherence): the
release DATE is authoritative in CHANGELOG.md and must agree with
CITATION.cff/codemeta.json; the maturity label, project URLs, site URL,
social-preview asset path, and the changelog link for the current version
are all checked offline (file reads only — never network).
"""

from __future__ import annotations

import json
import re
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

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


def _sync_script() -> ModuleType:
    """Load scripts/check_version_sync.py as a module (not an installed pkg)."""
    script = REPO_ROOT / "scripts" / "check_version_sync.py"
    spec = spec_from_file_location("_check_version_sync", script)
    assert spec and spec.loader, f"cannot load {script}"
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


class TestReleaseMetadataCoherence:
    """§4.3: release date, maturity label, URLs, preview asset, changelog link.

    All checks are pure file reads of repository state — no network, no
    external service. External-account verification lives in release/scheduled
    workflows, not here.
    """

    def test_changelog_entry_is_dated_for_current_version(self):
        version = _authoritative_version()
        script = _sync_script()
        assert script.authoritative_release_date(version), (
            f"CHANGELOG.md has no '## [{version}] - YYYY-MM-DD' entry; the "
            "changelog date is the authoritative release date"
        )

    def test_citation_and_codemeta_dates_match_changelog(self):
        version = _authoritative_version()
        script = _sync_script()
        rel_date = script.authoritative_release_date(version)
        assert rel_date, "changelog must carry the release date first"

        cff = (REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8")
        m = re.search(r"^date-released:\s*(\S+)\s*$", cff, re.M)
        assert m and m.group(1) == rel_date, (
            f"CITATION.cff date-released {m.group(1) if m else '<missing>'!r} "
            f"!= changelog release date {rel_date}"
        )

        cm = json.loads((REPO_ROOT / "codemeta.json").read_text(encoding="utf-8"))
        assert cm.get("datePublished") == rel_date, (
            f"codemeta.json datePublished {cm.get('datePublished')!r} "
            f"!= changelog release date {rel_date}"
        )

    def test_maturity_label_consistent_on_zero_line(self):
        version = _authoritative_version()
        if not version.startswith("0."):
            pytest.skip("maturity-label rule applies to the 0.x line")
        py = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        m = re.search(r'"Development Status :: (\d) - (\w+)"', py)
        assert m, "pyproject must declare a Development Status classifier"
        assert m.group(2).lower() == "alpha", (
            f"0.x line declares classifier '{m.group(0)}' but public wording says alpha"
        )
        cm = json.loads((REPO_ROOT / "codemeta.json").read_text(encoding="utf-8"))
        assert str(cm.get("developmentStatus", "")).lower() == "alpha"

    def test_project_urls_are_canonical(self):
        py = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        sec = re.search(r"^\[project\.urls\]\n(.*?)(?=^\[)", py, re.M | re.S)
        assert sec, "[project.urls] missing from pyproject.toml"
        wanted = {
            "Homepage": "https://waalwalker1.github.io/knovaryn/",
            "Documentation": "https://waalwalker1.github.io/knovaryn/",
            "Repository": "https://github.com/waalwalker1/knovaryn",
            "Issues": "https://github.com/waalwalker1/knovaryn/issues",
            "Changelog": "https://github.com/waalwalker1/knovaryn/blob/main/CHANGELOG.md",
            "Security": "https://github.com/waalwalker1/knovaryn/blob/main/SECURITY.md",
        }
        drifted = []
        for key, want in wanted.items():
            m = re.search(rf'^{key}\s*=\s*"([^"]+)"', sec.group(1), re.M)
            if not m or m.group(1) != want:
                got = m.group(1) if m else "<missing>"
                drifted.append(f"{key}: {got} (expected {want})")
        assert not drifted, "\n".join(drifted)

    def test_site_url_agrees_across_surfaces(self):
        site = "https://waalwalker1.github.io/knovaryn/"
        mk = (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8")
        assert re.search(rf"^site_url:\s*{re.escape(site)}\s*$", mk, re.M), (
            "mkdocs.yml site_url must be the canonical Pages URL"
        )
        cff = (REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8")
        assert re.search(rf'^url:\s*"{re.escape(site)}"\s*$', cff, re.M), (
            "CITATION.cff url must be the canonical Pages URL"
        )
        repo = "https://github.com/waalwalker1/knovaryn"
        cm = json.loads((REPO_ROOT / "codemeta.json").read_text(encoding="utf-8"))
        assert cm.get("codeRepository") == repo
        related = cm.get("relatedLink") or []
        for want in (site.rstrip("/"), "https://pypi.org/project/knovaryn/"):
            assert want in related, f"codemeta.json relatedLink missing {want}"

    def test_social_preview_wired_to_brand_asset(self):
        override = (REPO_ROOT / "overrides" / "main.html").read_text(encoding="utf-8")
        imgs = set(
            re.findall(
                r'(?:og:image|twitter:image)"?\s+content="\{\{ site_url \}\}([^"]+)"', override
            )
        )
        assert imgs, "overrides/main.html lost its og/twitter image meta"
        expected = "assets/brand/docs-social-preview.png"
        assert imgs == {expected}, (
            f"social previews point at {sorted(imgs)}, expected only {expected!r}"
        )
        assert (REPO_ROOT / "docs" / expected).is_file(), (
            f"{expected} missing — run scripts/visuals/build_brand_assets.py"
        )
        dims = dict(re.findall(r'og:image:(width|height)"\s+content="(\d+)"', override))
        assert dims == {"width": "1200", "height": "630"}

    def test_changelog_defines_link_for_current_version(self):
        version = _authoritative_version()
        cl = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        pattern = (
            rf"^\[{re.escape(version)}\]:\s*https://github\.com/waalwalker1/knovaryn"
            rf"/(?:compare/\S*v{re.escape(version)}|releases/tag/v{re.escape(version)})\s*$"
        )
        assert re.search(pattern, cl, re.M), (
            f"CHANGELOG.md lacks a compare/tag link definition for [{version}]"
        )
