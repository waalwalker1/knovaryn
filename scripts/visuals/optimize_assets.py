#!/usr/bin/env python3
"""Assemble captured frames into docs/assets/screenshots/offline-demo.gif.

Reads the frame sequence produced by capture_docs_screenshots.py, assembles
a silent, no-flashing GIF (800 ms per frame ≈ 24 s for 30 frames), optimizes
it, and writes a static poster PNG (first frame, downscaled) next to it.

Duration target: 20-40 s (§13.4). At 800 ms/frame the viewer can actually
read each console state — no misleading speed-up: the console really does
respond in well under a second, and the caption discloses the pacing.

Usage:
    uv run --no-sync python scripts/visuals/optimize_assets.py \
        --frames-dir /tmp/knovaryn-frames [--out docs/assets/screenshots]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FRAMES = Path("/tmp/knovaryn-frames")
DEFAULT_OUT = REPO_ROOT / "docs" / "assets" / "screenshots"
FRAME_MS = 800  # per-frame duration: readable, calm, ~24 s total for 30 frames
GIF_WIDTH = 1024  # captured width; kept 1:1 so text stays crisp at README width
MAX_GIF_BYTES = 5_000_000  # contract §15 budget "preferably < 5 MB"


def _frames(frames_dir: Path) -> list[Path]:
    frames = sorted(frames_dir.glob("frame-*.png"))
    if not frames:
        raise SystemExit(f"no frame-*.png in {frames_dir} — run capture_docs_screenshots.py first")
    return frames


def optimize_screenshot(path: Path) -> int:
    """Re-encode a UI screenshot with a 256-color palette, in place.

    The console is flat-color UI: MAXCOVERAGE quantization without dither is
    visually lossless (max per-channel delta ≤ 4/255 measured across the
    full-size captures) while roughly halving the file — the difference
    between §15's 350 KB budget and a 550 KB mobile capture. Crisp text is
    the reason for dither=NONE; Floyd–Steinberg would speckle glyph edges.
    """
    before = path.stat().st_size
    img = Image.open(path).convert("RGB")
    pal = img.quantize(colors=256, method=Image.MAXCOVERAGE, dither=Image.NONE)
    pal.save(path, optimize=True)
    return path.stat().st_size - before


def build_gif(frames: list[Path], out_dir: Path) -> Path:
    images = [Image.open(f).convert("RGB") for f in frames]
    if images[0].width != GIF_WIDTH:
        ratio = GIF_WIDTH / images[0].width
        size = (GIF_WIDTH, round(images[0].height * ratio))
        images = [
            img.resize(size, Image.LANCZOS) if img.width != GIF_WIDTH else img for img in images
        ]
    # Pillow coalesces byte-identical consecutive frames and accumulates their
    # durations — the calm pacing (5 identical shots per scene) survives as a
    # fewer-frame GIF with the same total runtime. Verify the distinct-scene
    # count so a capture regression (every scene identical) fails loudly.
    scene_count = len({img.tobytes() for img in images})
    if scene_count < 4:
        raise SystemExit(
            f"only {scene_count} distinct frames in {len(images)} — the capture "
            "script should produce 6 distinct scenes (console, projects, "
            "pipeline, quality, lineage, export)"
        )
    pal_images = [img.convert("P", palette=Image.ADAPTIVE, colors=128) for img in images]
    out = out_dir / "offline-demo.gif"
    pal_images[0].save(
        out,
        save_all=True,
        append_images=pal_images[1:],
        duration=FRAME_MS,
        loop=0,
        optimize=True,
        disposal=2,
    )
    return out


def build_poster(frames: list[Path], out_dir: Path) -> Path:
    poster = Image.open(frames[0]).convert("RGB")
    out = out_dir / "offline-demo-poster.png"
    poster.save(out, optimize=True)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames-dir", type=Path, default=DEFAULT_FRAMES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--shots",
        action="store_true",
        help="also palette-optimize the captured PNG screenshots in --out-dir",
    )
    args = parser.parse_args()

    failures = 0
    if args.shots:
        for shot in sorted(args.out_dir.glob("*.png")):
            if shot.name == "offline-demo-poster.png":
                continue  # written below from the (already-paletted) frames
            delta = optimize_screenshot(shot)
            print(f"optimized {shot.name} ({delta / 1024:+.0f} KB)")

    frames = _frames(args.frames_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    gif = build_gif(frames, args.out_dir)
    poster = build_poster(frames, args.out_dir)
    gif_size = gif.stat().st_size
    print(
        f"{gif} {gif_size / 1024:.0f} KB ({len(frames)} frames x {FRAME_MS} ms "
        f"= {len(frames) * FRAME_MS / 1000:.0f} s); poster {poster.name} "
        f"{poster.stat().st_size / 1024:.0f} KB"
    )
    if gif_size > MAX_GIF_BYTES:
        print(
            f"WARNING: gif exceeds {MAX_GIF_BYTES} budget — consider fewer frames "
            "or a lower color count"
        )
        failures = 1
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
