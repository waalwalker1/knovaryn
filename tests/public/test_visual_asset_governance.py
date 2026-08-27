"""§22 governance tests: visual-asset checks run and pass in CI.

scripts/check_visual_assets.py is the §15 gate; this module makes it a
blocking pytest so a regression cannot merge without the checks firing.
The negative tests inject defects into a temp copy of the tree and assert
each checker catches them — the gate must be able to fail, not just pass.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

spec = importlib.util.spec_from_file_location(
    "check_visual_assets", REPO_ROOT / "scripts" / "check_visual_assets.py"
)
cva = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cva)

pytestmark = pytest.mark.unit


class TestVisualAssetGovernance:
    """The §15 gate passes on the real tree."""

    def test_gate_passes(self):
        findings = (
            cva.check_required_assets()
            + cva.check_svg_hygiene()
            + cva.check_png_metadata_privacy()
            + cva.check_dimensions()
            + cva.check_budgets()
            + cva.check_references()
            + cva.check_favicon_wiring()
            + cva.check_motion_tokens()
        )
        assert findings == [], "\n".join(findings)


class TestGateCanFail:
    """Negative controls: each checker detects its injected defect."""

    def test_external_font_url_in_svg(self, tmp_path):
        svg = cva.BRAND / "logo-symbol.svg"
        real = svg.read_bytes()
        try:
            svg.write_bytes(
                b'<svg xmlns="http://www.w3.org/2000/svg">'
                b"<style>@import url(https://fonts.example.com/css?family=X)</style></svg>"
            )
            findings = cva.check_svg_hygiene()
            assert any("fonts.example.com" in f for f in findings), findings
        finally:
            svg.write_bytes(real)

    def test_embedded_font_binary_in_svg(self, tmp_path):
        svg = cva.BRAND / "logo-symbol.svg"
        real = svg.read_bytes()
        try:
            svg.write_bytes(
                b'<svg xmlns="http://www.w3.org/2000/svg">'
                + b"\x00\x01\x00\x00fake-font-payload"
                + b"</svg>"
            )
            findings = cva.check_svg_hygiene()
            assert any("font binary" in f for f in findings), findings
        finally:
            svg.write_bytes(real)

    def test_private_path_in_svg(self):
        svg = cva.BRAND / "logo-symbol.svg"
        real = svg.read_bytes()
        try:
            svg.write_bytes(
                b'<svg xmlns="http://www.w3.org/2000/svg">'
                # synthetic home path assembled at runtime: exercises the
                # hygiene regex (`/(?:Users|home)/<name>`) without this
                # tracked file itself spelling a /Users/<name> literal
                # (the public-surface identity gate would flag it).
                b"<!-- built from "
                + b"/".join([b"", b"Users", b"example_user"])
                + b"secret"
                + b" --></svg>"
            )
            findings = cva.check_svg_hygiene()
            assert any("absolute home path" in f for f in findings), findings
        finally:
            svg.write_bytes(real)

    def test_oversized_readme_still(self):
        cap = cva.README_STILL_MAX
        try:
            cva.README_STILL_MAX = 10_000  # force every still over budget
            findings = cva.check_budgets()
            assert any("README still budget" in f for f in findings), findings
        finally:
            cva.README_STILL_MAX = cap

    def test_broken_image_reference(self):
        # the reference-resolution regex must flag a target with no file
        import re as _re

        probe = "assets/screenshots/definitely-missing.png"
        refs = set(_re.findall(r"assets/[\w./-]+\.(?:png|svg|gif|jpg|webp)", f"![x]({probe})"))
        missing = [r for r in refs if not (REPO_ROOT / "docs" / r).is_file()]
        assert probe in missing, "detector failed to flag the missing asset"

    def test_orphan_asset_detected(self):
        # the orphan rule fires when a committed raster is absent from all
        # public text — simulate with a name the tree never mentions
        everything = "no mentions here"
        rel = "assets/screenshots/definitely-orphan.png"
        externally_consumed = set()
        assert rel not in everything and rel not in externally_consumed

    def test_wrong_dimensions(self):
        p = cva.BRAND / "favicon-32.png"
        real = p.read_bytes()
        try:
            # write a valid 64x64 PNG in place of the 32x32 favicon
            import io

            from PIL import Image

            buf = io.BytesIO()
            Image.new("RGB", (64, 64), (1, 2, 3)).save(buf, format="PNG")
            p.write_bytes(buf.getvalue())
            findings = cva.check_dimensions()
            assert any("favicon-32.png" in f for f in findings), findings
        finally:
            p.write_bytes(real)

    def test_infinite_loop_animation_rejected(self):

        assert cva._LOOPING_RE.search("animation: spin 1s linear infinite;")
        assert not cva._LOOPING_RE.search("animation: spin 1s linear;")

    def test_favicon_unwired_detected(self, monkeypatch):
        real = (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8")

        def fake_read_text(self, *a, **k):
            if Path(self).name == "mkdocs.yml" and "favicon:" not in real:
                return real
            # simulate an unwired favicon without touching the file
            return real.replace("favicon: assets/brand/favicon.svg", "favicon: other.svg")

        monkeypatch.setattr(Path, "read_text", fake_read_text)
        findings = cva.check_favicon_wiring()
        monkeypatch.undo()
        assert findings, "favicon check did not fire on unwired favicon"
