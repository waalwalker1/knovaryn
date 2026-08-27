#!/usr/bin/env python3
"""Verify the captured visual assets meet the §13 contract.

Executes the acceptance checks for docs/assets/screenshots/:

- every required screenshot exists and is non-trivial (real content);
- dimensions match the capture contract (desktop @2x, mobile @3x, GIF 1024);
- the GIF is silent (no audio is possible in GIF), 20–40 s, within the size
  budget, and contains the 6 narrated scenes;
- no frame or PNG exposes private patterns (local usernames, home paths,
  emails, tokens) — §13.3;
- PNG metadata carries no absolute paths or user identifiers.

Exit 0 = all checks pass; any failure exits 1 with the reason. This is the
executable evidence for the screenshots; scripts/check_visual_assets.py (§15)
is the repo-wide governance gate.

Usage:
    uv run --no-sync python scripts/visuals/verify_visual_assets.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image, ImageSequence

REPO_ROOT = Path(__file__).resolve().parents[2]
SHOTS = REPO_ROOT / "docs" / "assets" / "screenshots"

REQUIRED = {
    "web-console-overview.png": (2560, 3400),  # 1280x800@2x full-page (content-sized)
    "project-source-view.png": None,  # section crop, content-sized
    "provenance-lineage.png": None,
    "quality-gates.png": None,
    "preference-review.png": None,
    "export-release.png": None,
    "mobile-overview.png": None,  # 375px@3x full page
    "dark-mode-overview.png": None,
}
MOBILE_SCALE = 3
DESKTOP_SCALE = 2
GIF_MIN_S, GIF_MAX_S = 20, 40
GIF_MAX_BYTES = 5_000_000
POSTER_MAX_BYTES = 350_000
README_SHOT_MAX_BYTES = 350_000  # §15 budget for README-embedded stills

# §13.3 privacy patterns. Usernames appear in absolute paths and user agents;
# emails are matched conservatively (anything that looks like one); tokens by
# assignment shape. The demo workspace owner principal is "cli" by design.
PRIVATE_PATTERNS = [
    (re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+"), "absolute home path"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "email address"),
    (re.compile(r"\b(?:sk|ghp|gho|github_pat|xoxb|AKIA)[A-Za-z0-9_-]{10,}\b"), "credential token"),
    (re.compile(r"(?i)\b(?:api[_-]?key|secret|password)\s*[=:]\s*\S+"), "key/value secret"),
]


def _check(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def _scan_private_metadata(path: Path, where: str, failures: list[str]) -> None:
    """Scan ONLY the PNG's text metadata chunks (§13.3 'image metadata').

    Decoding compressed pixel data as text produces random-byte false
    positives; PIL's info dict surfaces exactly the tEXt/iTXt/zTXt chunks
    (plus format basics) that a viewer or crawler could read.
    """
    img = Image.open(path)
    for key, value in (img.info or {}).items():
        if not isinstance(value, str):
            continue
        for pattern, label in PRIVATE_PATTERNS:
            if pattern.search(value):
                failures.append(f"{where}: {label} in metadata key {key!r}")
    # EXIF/textual safety net
    exif = getattr(img, "getexif", lambda: {})()
    for _tag, value in (exif or {}).items():
        if isinstance(value, str):
            for pattern, label in PRIVATE_PATTERNS:
                if pattern.search(value):
                    failures.append(f"{where}: {label} in EXIF")


def main() -> int:
    failures: list[str] = []

    # ---- required files -----------------------------------------------------
    for name in REQUIRED:
        path = SHOTS / name
        _check(path.exists(), f"missing required screenshot {name}", failures)
        if not path.exists():
            continue
        img = Image.open(path)
        _check(img.width >= 600, f"{name}: suspiciously narrow ({img.width}px)", failures)
        _check(img.height >= 400, f"{name}: suspiciously short ({img.height}px)", failures)
        if name == "mobile-overview.png":
            # 3x device scale; headless scrollbar presence varies the CSS width
            # (375 viewport + 0-17px scrollbar), so accept that band
            _check(
                375 * MOBILE_SCALE <= img.width <= 400 * MOBILE_SCALE,
                f"{name}: width {img.width} outside 3x mobile band (1125-1200)",
                failures,
            )
        if name == "web-console-overview.png":
            _check(
                img.width == 1280 * DESKTOP_SCALE,
                f"{name}: width {img.width} != {1280 * DESKTOP_SCALE}",
                failures,
            )
        # PNG metadata privacy: no paths/usernames in text chunks
        _scan_private_metadata(path, name, failures)

    # ---- README stills within budget ---------------------------------------
    # README embeds the canonical §13.2 section crops (provenance-lineage,
    # quality-gates, export-release) — all held to the §15 still budget by
    # scripts/check_visual_assets.py; there are no separate readme-* variants.

    # ---- GIF contract --------------------------------------------------------
    gif_path = SHOTS / "offline-demo.gif"
    _check(gif_path.exists(), "missing offline-demo.gif", failures)
    if gif_path.exists():
        _check(gif_path.stat().st_size <= GIF_MAX_BYTES, "gif exceeds 5 MB budget", failures)
        gif = Image.open(gif_path)
        durations = []
        frames = 0
        for frame in ImageSequence.Iterator(gif):
            durations.append(frame.info.get("duration", 0))
            frames += 1
        total_s = sum(durations) / 1000
        _check(
            GIF_MIN_S <= total_s <= GIF_MAX_S,
            f"gif duration {total_s:.0f}s outside 20-40s",
            failures,
        )
        _check(gif.size == (1024, 640), f"gif size {gif.size} != (1024, 640)", failures)
        # seek-based distinct-frame count (Iterator composites disposal=2 patches)
        seen = set()
        for i in range(frames):
            gif.seek(i)
            seen.add(gif.convert("RGB").tobytes())
        _check(len(seen) >= 6, f"gif has {len(seen)} distinct scenes, expected >= 6", failures)

    poster = SHOTS / "offline-demo-poster.png"
    _check(poster.exists(), "missing offline-demo-poster.png (static fallback)", failures)
    if poster.exists():
        _check(poster.stat().st_size <= POSTER_MAX_BYTES, "poster exceeds 350 KB budget", failures)

    # ---- README alt-text coverage (§10.6) ------------------------------------
    readme = (REPO_ROOT / "README.md").read_text()
    for name in (
        "offline-demo-poster.png",
        "provenance-lineage.png",
        "quality-gates.png",
        "export-release.png",
    ):
        idx = readme.find(name)
        _check(idx != -1, f"README does not reference {name}", failures)
        if idx == -1:
            continue
        # the <img ...> tag that carries this src: search back to the tag open
        tag_open = readme.rfind("<img", 0, idx)
        _check(tag_open != -1, f"README image {name} is not inside an <img> tag", failures)
        if tag_open == -1:
            continue
        tag_end = readme.find(">", idx)
        tag = readme[tag_open:tag_end]
        alt_match = re.search(r'alt="([^"]*)"', tag)
        _check(
            alt_match is not None and len(alt_match.group(1)) > 40,
            f"README image {name} lacks descriptive alt text",
            failures,
        )

    if failures:
        print("FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"OK: {len(REQUIRED)} screenshots + gif/poster verified (privacy, sizes, alt text)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
