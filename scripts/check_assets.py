#!/usr/bin/env python3
"""Automated asset-consistency checks (contract §6.5, v0.2.1).

Python-only, deterministic, no network:

* every image referenced by README/docs has meaningful alt text;
* every rendered diagram PNG has its Mermaid source present, and every
  edited source is flagged for re-render when its PNG is older
  (mtime-based drift signal; byte-exact drift is checked in CI with a
  pinned mermaid-cli via ``--render``);
* no committed artifact exists without its source;
* the raster social card is exactly the Open Graph standard 1200×630 and
  referenced as og:image by the site override;
* diagrams carry NO hard-coded counts ("23 tools", "10 gates", …) and no
  overstated "exact page" claims — counts live in generated pages only.

``--render`` additionally renders all .mmd sources with mermaid-cli into a
temp dir and byte-compares against the committed PNGs (requires ``mmdc`` on
PATH at the pinned version used by CI).
"""

from __future__ import annotations

import argparse
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS = REPO_ROOT / "docs" / "assets"
DIAGRAMS = ASSETS / "diagrams"
BRAND = ASSETS / "brand"

# name pairs: <stem>.png is rendered from diagrams/<stem>.mmd (or ./<stem>.mmd)
DIAGRAM_STEMS = [
    "system-architecture",
    "pipeline-flow",
    "durable-jobs",
    "mcp-session",
    "security",
    "value-proposition",
    "deployment-topology",
    "provenance-lineage",
    "release-supply-chain",
]

SOCIAL_CARD = BRAND / "docs-social-preview.png"
# Canonical Open Graph raster: 1200×630. (GitHub's *repository* social
# preview suggests 1280×640 — that is github-social-preview.png in the same
# directory — but this card is published as og:image via overrides/main.html:
# the OG spec's 1200×630 is what every link unfurler is built around.)
SOCIAL_SIZE = (1200, 630)

# Diagrams must be count-free and precision-honest (defects fixed in §6.2).
# Counts belong in GENERATED reference pages, never frozen into images.
_STALE_CLAIM_PATTERNS = [
    re.compile(r"\b\d+\s*(?:registerd |registered )?tools\b", re.IGNORECASE),
    re.compile(r"\b\d+\s*quality gates\b", re.IGNORECASE),
    re.compile(r"\b\d+-tool\b", re.IGNORECASE),
    re.compile(r"\b\d+\s*gates\b"),
    re.compile(r"doc · page · sentence", re.IGNORECASE),
    re.compile(r"exact page \+ section", re.IGNORECASE),
]


def _markdown_files() -> list[Path]:
    files = [REPO_ROOT / "README.md"]
    for sub in ("docs",):
        files.extend(p for p in (REPO_ROOT / sub).rglob("*.md") if "assets" not in p.parts)
    return sorted(files)


def check_alt_text() -> list[str]:
    problems: list[str] = []
    md_img = re.compile(r"!\[(.*?)\]\(([^)]+)\)")
    html_img = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
    alt_attr = re.compile(r"""alt\s*=\s*["']([^"']*)["']""", re.IGNORECASE)
    for path in _markdown_files():
        rel = path.relative_to(REPO_ROOT)
        text = path.read_text(encoding="utf-8")
        for match in md_img.finditer(text):
            alt, target = match.group(1).strip(), match.group(2)
            if target.startswith(("http://", "https://")):
                continue  # remote badges carry their own alt on the service
            if len(alt) < 8 or alt.lower() in {"image", "logo", "diagram"}:
                problems.append(f"{rel}: weak alt text {alt!r} for {target}")
        for tag in html_img.finditer(text):
            src_attr = re.compile(r"""src\s*=\s*["']([^"']*)["']""", re.IGNORECASE).search(
                tag.group(0)
            )
            if src_attr and src_attr.group(1).startswith(("http://", "https://")):
                continue  # shield.io-style badges: short alt is conventional
            m = alt_attr.search(tag.group(0))
            if not m or len(m.group(1).strip()) < 8:
                problems.append(f"{rel}: <img> without meaningful alt: {tag.group(0)[:80]}")
    return problems


def _png_size(path: Path) -> tuple[int, int] | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", data[16:24])
    return w, h


def check_sources_and_artifacts() -> list[str]:
    problems: list[str] = []
    for stem in DIAGRAM_STEMS:
        png = next(
            (p for p in (ASSETS / f"{stem}.png", DIAGRAMS / f"{stem}.png") if p.exists()),
            None,
        )
        # sources live beside their renders: diagrams/<stem>.mmd for the
        # five architecture diagrams, assets/<stem>.mmd for pipeline-flow
        src = next(
            (p for p in (DIAGRAMS / f"{stem}.mmd", ASSETS / f"{stem}.mmd") if p.exists()),
            None,
        )
        if src is not None and png is None:
            problems.append(f"diagram {stem}: source .mmd committed but no rendered .png")
        elif png is not None and src is None:
            problems.append(f"diagram {stem}: rendered .png committed WITHOUT its .mmd source")
        elif src is not None and png is not None and src.stat().st_mtime > png.stat().st_mtime:
            problems.append(
                f"diagram {stem}: .mmd edited after its .png was rendered — "
                "run scripts/render_diagrams.py"
            )
    # orphan rendered assets (nothing references them anywhere public)
    public_text = "\n".join(p.read_text(encoding="utf-8") for p in _markdown_files())
    override = REPO_ROOT / "overrides" / "main.html"
    if override.is_file():
        public_text += "\n" + override.read_text(encoding="utf-8")
    for img in sorted(ASSETS.glob("*.png")) + sorted(ASSETS.glob("*.svg")):
        if f"assets/{img.name}" not in public_text:
            problems.append(f"asset {img.name} is not referenced by README or any docs page")
    return problems


def check_social_card() -> list[str]:
    problems: list[str] = []
    if not SOCIAL_CARD.is_file():
        return [f"missing raster social card: {SOCIAL_CARD.name}"]
    size = _png_size(SOCIAL_CARD)
    if size != SOCIAL_SIZE:
        problems.append(f"social card is {size}, expected {SOCIAL_SIZE}")
    override = REPO_ROOT / "overrides" / "main.html"
    if override.is_file():
        text = override.read_text(encoding="utf-8")
        if "og:image" not in text:
            problems.append("overrides/main.html declares no og:image")
        elif f"assets/brand/{SOCIAL_CARD.name}" not in text:
            problems.append("overrides/main.html og:image does not reference the social card")
    else:
        problems.append("overrides/main.html missing — cannot assert social-card wiring")
    return problems


def check_no_stale_claims() -> list[str]:
    """Diagrams must be count-free and precision-honest (§6.2)."""
    problems: list[str] = []
    for src in sorted(DIAGRAMS.glob("*.mmd")) + [ASSETS / "pipeline-flow.mmd"]:
        text = src.read_text(encoding="utf-8")
        for pat in _STALE_CLAIM_PATTERNS:
            m = pat.search(text)
            if m:
                problems.append(f"{src.relative_to(REPO_ROOT)}: stale claim {m.group(0)!r}")
    for banner in sorted(BRAND.glob("github-readme-banner*.svg")) + sorted(
        BRAND.glob("*social-preview-source.svg")
    ):
        text = banner.read_text(encoding="utf-8")
        for pat in _STALE_CLAIM_PATTERNS:
            m = pat.search(text)
            if m:
                problems.append(f"{banner.relative_to(REPO_ROOT)}: stale claim {m.group(0)!r}")
    return problems


def render_and_compare() -> list[str]:
    """Byte-compare fresh mermaid-cli renders with committed PNGs."""
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="knv-assets-") as td:
        out = Path(td)
        for stem in DIAGRAM_STEMS:
            src = next(
                (p for p in (DIAGRAMS / f"{stem}.mmd", ASSETS / f"{stem}.mmd") if p.is_file()),
                None,
            )
            png = ASSETS / f"{stem}.png"
            if src is None or not png.is_file():
                continue
            dest = out / f"{stem}.png"
            cp = subprocess.run(
                ["mmdc", "-i", str(src), "-o", str(dest), "-b", "white", "-s", "2"],
                capture_output=True,
                text=True,
            )
            if cp.returncode != 0 or not dest.is_file():
                problems.append(f"render failed for {stem}: {(cp.stderr or '').strip()[:200]}")
                continue
            import hashlib

            new = hashlib.sha256(dest.read_bytes()).hexdigest()
            old = hashlib.sha256(png.read_bytes()).hexdigest()
            if new != old:
                problems.append(
                    f"{stem}.png drifted from its .mmd render — run scripts/render_diagrams.py"
                )
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--render", action="store_true", help="also render .mmd and compare bytes")
    args = ap.parse_args()

    suites = {
        "alt text": check_alt_text(),
        "sources/artifacts": check_sources_and_artifacts(),
        "social card": check_social_card(),
        "stale claims": check_no_stale_claims(),
    }
    if args.render:
        suites["render drift"] = render_and_compare()

    total = 0
    for name, findings in suites.items():
        print(f"=== assets/{name}: {'FAIL' if findings else 'OK'} ===")
        for f in findings:
            print(f"  FAIL: {f}")
        total += len(findings)

    if total:
        print(f"\nFAILED: {total} asset problem(s).")
        return 1
    print("\nPASSED: asset consistency checks clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
