"""Regression tests: repository metadata and social preview (defect 4.13 family).

v0.1's OpenGraph/Twitter meta pointed at an SVG image — GitHub, X, and the
other link-unfurlers that consume those tags never render SVG, so shared
links showed a blank card. Corrected contract:

* site metadata (description/URL/repo) is set in mkdocs.yml;
* a raster social card (PNG, 1200x630 — the large-card size X requires)
  exists and is what og:image / twitter:image actually reference.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.unit


class TestMetadataAndSocialCards:
    """Repository metadata and social previews are complete and renderable."""

    def test_site_metadata_set(self):
        mkdocs = (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8")
        assert "site_description:" in mkdocs
        assert re.search(r"site_url:\s*\S+", mkdocs)
        assert re.search(r"repo_url:\s*\S+", mkdocs)

    def test_social_preview_exists_and_is_referenced(self):
        card = REPO_ROOT / "docs" / "assets" / "knovaryn-social-card.png"
        assert card.is_file(), "social card PNG missing from docs/assets/"

        # must be a real raster image at large-card size
        from struct import unpack

        data = card.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", "social card is not a PNG"
        width, height = unpack(">II", data[16:24])
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
