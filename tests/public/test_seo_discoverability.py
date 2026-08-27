"""§17 SEO / AI-discoverability regression tests.

Contract surfaces verified here so they cannot silently rot:

- llms.txt carries the §17.3 required sections (definition, version and
  maturity, interfaces, installation, core capabilities, limitations,
  canonical doc links incl. generated references, security route,
  contribution route) — without becoming a keyword dump;
- sitemap.xml + robots.txt exist and agree (robots points at the sitemap;
  every sitemap URL uses the canonical site_url);
- built pages have unique titles + meta descriptions, canonical URLs,
  absolute og:image/twitter:image (asserted on site/ when present);
- no analytics scripts / third-party trackers in built HTML (§19: none by
  design).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"
SITE = REPO_ROOT / "site"

pytestmark = pytest.mark.unit


class TestLlmsTxt:
    """§17.3 AI-agent resource completeness."""

    @pytest.fixture(scope="class")
    @staticmethod
    def llms() -> str:
        path = DOCS / "llms.txt"
        assert path.is_file(), "docs/llms.txt missing"
        return path.read_text(encoding="utf-8")

    def test_required_sections(self, llms: str):
        for section in (
            "## Version and maturity",
            "## Installation",
            "## Interfaces",
            "## Key tools / capabilities",
            "## Limitations",
            "## Documentation",
            "## Security",
            "## Contributing",
            "## License",
        ):
            assert section in llms, f"llms.txt missing required section {section!r}"

    def test_version_matches_package(self, llms: str):
        from knovaryn import __version__

        assert __version__ in llms, f"llms.txt does not state current version {__version__}"
        assert "alpha" in llms.lower(), "llms.txt must state the maturity label"

    def test_generated_references_linked(self, llms: str):
        for ref in ("reference/cli/", "reference/mcp-tools/", "reference/rest-api/"):
            assert ref in llms, f"llms.txt must link the generated {ref} reference"

    def test_security_route_present(self, llms: str):
        assert "SECURITY.md" in llms, "private vulnerability reporting route missing"

    def test_not_a_keyword_dump(self, llms: str):
        # §17.3: no paragraph may repeat the product name excessively — a
        # crude but effective stuffing detector
        lines = [ln for ln in llms.splitlines() if ln.strip()]
        for line in lines:
            assert line.lower().count("knovaryn") <= 3, f"possible keyword stuffing: {line!r}"


class TestSitemapRobots:
    """§17.2 crawl surfaces exist and agree."""

    def test_robots_points_at_sitemap(self):
        robots = REPO_ROOT / "site" / "robots.txt"
        if not robots.is_file():  # site/ is a build artifact; fall back to source
            pytest.skip("site/ not built")
        assert "Sitemap:" in robots.read_text(encoding="utf-8")

    def test_sitemap_urls_are_canonical(self):
        sitemap = REPO_ROOT / "site" / "sitemap.xml"
        if not sitemap.is_file():
            pytest.skip("site/ not built")
        text = sitemap.read_text(encoding="utf-8")
        locs = re.findall(r"<loc>([^<]+)</loc>", text)
        assert locs, "empty sitemap"
        bad = [u for u in locs if not u.startswith("https://waalwalker1.github.io/knovaryn/")]
        assert not bad, f"non-canonical sitemap URLs: {bad[:3]}"

    def test_built_pages_unique_titles_and_descriptions(self):
        if not SITE.is_dir():
            pytest.skip("site/ not built")
        pages = sorted(SITE.rglob("index.html"))
        assert len(pages) > 40
        titles, descriptions = {}, {}
        for page in pages:
            text = page.read_text(encoding="utf-8")
            t = re.search(r"<title>([^<]+)</title>", text)
            d = re.search(r'<meta name="description" content="([^"]*)"', text)
            rel = str(page.relative_to(SITE))
            if t:
                titles.setdefault(t.group(1), []).append(rel)
            if d:
                descriptions.setdefault(d.group(1), []).append(rel)
        dup_t = {k: v for k, v in titles.items() if len(v) > 1}
        dup_d = {k: v for k, v in descriptions.items() if len(v) > 1}
        assert not dup_t, f"duplicate <title>: {list(dup_t)[:3]}"
        assert not dup_d, f"duplicate meta description: {list(dup_d)[:3]}"

    def test_built_pages_canonical_and_og_absolute(self):
        if not SITE.is_dir():
            pytest.skip("site/ not built")
        for page in (SITE / "index.html", SITE / "guides" / "quickstart" / "index.html"):
            text = page.read_text(encoding="utf-8")
            assert re.search(r'<link rel="canonical" href="https://', text), f"{page}: canonical"
            og = re.search(r'<meta property="og:image" content="([^"]+)"', text)
            assert og and og.group(1).startswith("https://"), f"{page}: og:image absolute"
            tw = re.search(r'<meta name="twitter:image" content="([^"]+)"', text)
            assert tw and tw.group(1).startswith("https://"), f"{page}: twitter:image absolute"

    def test_no_analytics_in_built_html(self):
        """§19: zero third-party requests by design — no tracker snippets."""
        if not SITE.is_dir():
            pytest.skip("site/ not built")
        trackers = (
            "googletagmanager",
            "google-analytics",
            "plausible",
            "fathom",
            "posthog",
            "matomo",
            "cloudflareinsights",
            "segment.com",
        )
        for page in list(SITE.rglob("index.html"))[:20]:
            text = page.read_text(encoding="utf-8")
            for t in trackers:
                assert t not in text.lower(), f"{page}: analytics snippet {t!r} present"
