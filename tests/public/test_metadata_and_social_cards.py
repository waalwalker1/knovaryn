"""Regression tests: repository metadata and social preview (defect 4.13 family).

v0.1's OpenGraph/Twitter meta pointed at an SVG image — GitHub, X, and the
other link-unfurlers that consume those tags never render SVG, so shared
links showed a blank card. Corrected contract:

* site metadata (description/URL/repo) is set in mkdocs.yml;
* the canonical raster social previews are the generated brand assets
  (docs/assets/brand/): docs-social-preview.png (1200x630 — the large-card
  size X requires) is what og:image / twitter:image reference, and
  github-social-preview.png meets GitHub's own recommendation (1280x640,
  under 1 MB);
* the README banner is served through <picture> with dark/narrow variants so
  it stays readable on both GitHub themes and mobile widths.
"""

from __future__ import annotations

import re
from pathlib import Path
from struct import unpack

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.unit


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    width, height = unpack(">II", data[16:24])
    return width, height


class TestMetadataAndSocialCards:
    """Repository metadata and social previews are complete and renderable."""

    def test_site_metadata_set(self):
        mkdocs = (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8")
        assert "site_description:" in mkdocs
        assert re.search(r"site_url:\s*\S+", mkdocs)
        assert re.search(r"repo_url:\s*\S+", mkdocs)

    def test_docs_social_preview_exists_and_is_referenced(self):
        card = REPO_ROOT / "docs" / "assets" / "brand" / "docs-social-preview.png"
        assert card.is_file(), "canonical social preview missing from docs/assets/brand/"

        width, height = _png_size(card)
        assert (width, height) >= (1200, 630), f"card too small: {width}x{height}"

        override = (REPO_ROOT / "overrides" / "main.html").read_text(encoding="utf-8")
        for prop in ("og:image", "twitter:image"):
            m = re.search(rf'{prop}" content="{{{{ site_url }}}}([^"]+)"', override)
            assert m, f"{prop} meta tag missing"
            ref = m.group(1)
            assert not ref.endswith(".svg"), (
                f"{prop} points at {ref}: link unfurlers do not render SVG"
            )
            assert (REPO_ROOT / "docs" / ref).is_file(), f"{prop} target missing: {ref}"

    def test_github_social_preview_meets_github_recommendation(self):
        """GitHub recommends 1280x640 (under 1 MB) for repository social previews."""
        preview = REPO_ROOT / "docs" / "assets" / "brand" / "github-social-preview.png"
        assert preview.is_file(), "GitHub social preview missing from docs/assets/brand/"
        width, height = _png_size(preview)
        assert (width, height) == (1280, 640), (
            f"GitHub social preview should be 1280x640, got {width}x{height}"
        )
        size_mb = preview.stat().st_size / (1000 * 1000)
        assert size_mb < 1.0, f"GitHub social preview exceeds 1 MB: {size_mb:.2f}"

    def test_readme_banner_has_theme_and_width_variants(self):
        """README banner must stay readable on light/dark GitHub and narrow widths."""
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "<picture>" in readme, "README banner must use <picture> for variants"
        for variant in (
            "github-readme-banner.svg",
            "github-readme-banner-dark.svg",
            "github-readme-banner-narrow.svg",
            "github-readme-banner-narrow-dark.svg",
        ):
            assert variant in readme, f"README banner missing variant {variant}"
            path = REPO_ROOT / "docs" / "assets" / "brand" / variant
            assert path.is_file(), f"banner variant asset missing: {variant}"
        # the fallback <img> must carry descriptive alt text (screen readers
        # and clients without <picture> support)
        banner_alt = r'<img src="docs/assets/brand/github-readme-banner\.svg"\s+alt="[^"]{40,}"'
        assert re.search(banner_alt, readme), (
            "README banner fallback img lacks descriptive alt text"
        )
