#!/usr/bin/env python3
"""Capture the documented product screenshots from a live demo workspace.

Drives the real web console (served by launch_visual_demo.start_server)
through deterministic interactions — list projects, add a source, validate,
list examples, view lineage, apply a review, export — and screenshots each
resulting state. Every pixel comes from the product; nothing is mocked.

Outputs (docs/assets/screenshots/):
    web-console-overview.png   full console, project listed, server healthy
    project-source-view.png    intake form + created source record
    provenance-lineage.png     example lineage chain (span locations)
    quality-gates.png          dataset quality report
    preference-review.png      review decision recorded on an example
    export-release.png         versioned export with checksums
    mobile-overview.png        375px full console
    dark-mode-overview.png     dark-scheme console

GIF frames for offline-demo.gif are written to a temp directory; assemble
them with optimize_assets.py.

Usage:
    uv run --no-sync python scripts/visuals/capture_docs_screenshots.py \
        --workspace /tmp/knovaryn-visual-xxxx [--port 8970]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "visuals"))

from launch_visual_demo import start_server, wait_for_health  # noqa: E402

OUT_DIR = REPO_ROOT / "docs" / "assets" / "screenshots"
DESKTOP = {"width": 1280, "height": 800}
CONSOLE_URL = "http://127.0.0.1:{port}/"


def _wait_ready(page) -> None:
    """Wait until the console's health check has painted its final state."""
    page.wait_for_function(
        "() => document.getElementById('status').textContent.includes('server ')"
    )
    page.wait_for_timeout(300)


LIST_PROJECTS = "button[data-act=list-projects]"


def _click_and_wait(page, button_id: str, out_id: str) -> str:
    """Click a console button (by id or selector) and return its new JSON text.

    Waits for the output panel to CHANGE — panels often already hold a
    previous response, so a length-only predicate would race stale text.
    """
    selector = button_id if button_id.startswith(("#", "button[")) else f"#{button_id}"
    before = page.inner_text(f"#{out_id}").strip()
    page.click(selector)
    page.wait_for_function(
        """(args) => {
             const t = document.getElementById(args.id).textContent.trim();
             return t.length > 2 && t !== args.before;
           }""",
        arg={"id": out_id, "before": before},
    )
    return page.inner_text(f"#{out_id}")


def _fill(page, input_id: str, value: str) -> None:
    page.fill(f"#{input_id}", value)


def capture(workspace: Path, port: int, frames_dir: Path) -> dict:
    from playwright.sync_api import sync_playwright

    state = json.loads((workspace / "state.json").read_text())
    project_id = state["project_id"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frames_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}

    server = start_server(workspace, port)
    try:
        if not wait_for_health(port):
            raise SystemExit(f"server not healthy on {port}")
        with sync_playwright() as p:
            browser = p.chromium.launch()

            # ---- desktop, light ------------------------------------------------
            ctx = browser.new_context(viewport=DESKTOP, device_scale_factor=2, color_scheme="light")
            page = ctx.new_page()
            page.goto(CONSOLE_URL.format(port=port), wait_until="networkidle")
            _wait_ready(page)

            # overview: list the demo project
            projects_json = _click_and_wait(page, LIST_PROJECTS, "projectsOut")
            if project_id not in projects_json:
                raise SystemExit("demo project missing from console project list")
            page.locator("button[data-act=list-projects]").scroll_into_view_if_needed()
            page.wait_for_timeout(200)
            page.screenshot(path=OUT_DIR / "web-console-overview.png", full_page=True)
            written["web-console-overview.png"] = "full console, project listed"

            # source intake: a real add through the form
            _fill(page, "pid", project_id)
            _fill(page, "srcname", "release-checklist.md")
            _fill(
                page,
                "srccontent",
                "# Release checklist\n\nCut a version, hash the artifact, "
                "verify the manifest sidecar before publishing.",
            )
            _fill(page, "srclic", "Apache-2.0")
            page.select_option("#srcpriv", "public")
            source_json = _click_and_wait(page, "addSource", "srcOut")
            if "src_" not in source_json:
                raise SystemExit(f"source intake failed: {source_json[:200]}")
            page.locator("#srcOut").scroll_into_view_if_needed()
            page.locator("section[aria-labelledby=src-title]").screenshot(
                path=OUT_DIR / "project-source-view.png"
            )
            written["project-source-view.png"] = "intake form + created source"

            # quality report
            _fill(page, "dspid", project_id)
            quality_json = _click_and_wait(page, "validate", "dsOut")
            if not quality_json.strip():
                raise SystemExit("validate produced no output")
            page.locator("#dsOut").scroll_into_view_if_needed()
            page.locator("section[aria-labelledby=ds-title]").screenshot(
                path=OUT_DIR / "quality-gates.png"
            )
            written["quality-gates.png"] = "dataset quality report"

            # examples + lineage
            _fill(page, "expid", project_id)
            examples_json = _click_and_wait(page, "listExamples", "exOut")
            examples = json.loads(examples_json).get("examples", [])
            if not examples:
                raise SystemExit("no examples listed")
            review_candidate = next(
                (
                    e
                    for e in examples
                    if e.get("topology") in ("kto", "dpo") or e.get("status") == "review"
                ),
                examples[0],
            )
            _fill(page, "reviewEx", review_candidate["id"])
            lineage_json = _click_and_wait(page, "viewLineage", "revOut")
            if "source_spans" not in lineage_json:
                raise SystemExit(f"lineage incomplete: {lineage_json[:200]}")
            page.locator("#revOut").scroll_into_view_if_needed()
            page.locator("section[aria-labelledby=ex-title]").screenshot(
                path=OUT_DIR / "provenance-lineage.png"
            )
            written["provenance-lineage.png"] = "lineage chain for one example"

            # review decision (real revision on the review-state example)
            page.select_option("#reviewDecision", "approve")
            _fill(page, "reviewNote", "Spot-checked against the cited span.")
            review_json = _click_and_wait(page, "doReview", "revOut")
            if not review_json.strip():
                raise SystemExit("review produced no output")
            page.locator("#revOut").scroll_into_view_if_needed()
            page.locator("section[aria-labelledby=ex-title]").screenshot(
                path=OUT_DIR / "preference-review.png"
            )
            written["preference-review.png"] = "review decision recorded"

            # export with checksums
            export_json = _click_and_wait(page, "export", "dsOut")
            if not any(k in export_json for k in ("download_path", "sha256", "artifact_id")):
                raise SystemExit(f"export output unexpected: {export_json[:200]}")
            page.locator("#dsOut").scroll_into_view_if_needed()
            page.locator("section[aria-labelledby=ds-title]").screenshot(
                path=OUT_DIR / "export-release.png"
            )
            written["export-release.png"] = "versioned export + checksums"
            ctx.close()

            # ---- mobile, light -------------------------------------------------
            mctx = browser.new_context(
                viewport={"width": 375, "height": 812},
                device_scale_factor=3,
                color_scheme="light",
            )
            mpage = mctx.new_page()
            mpage.goto(CONSOLE_URL.format(port=port), wait_until="networkidle")
            _wait_ready(mpage)
            _click_and_wait(mpage, LIST_PROJECTS, "projectsOut")
            mpage.screenshot(path=OUT_DIR / "mobile-overview.png", full_page=True)
            written["mobile-overview.png"] = "375px console"
            mctx.close()

            # ---- desktop, dark -------------------------------------------------
            dctx = browser.new_context(viewport=DESKTOP, device_scale_factor=2, color_scheme="dark")
            dpage = dctx.new_page()
            dpage.goto(CONSOLE_URL.format(port=port), wait_until="networkidle")
            _wait_ready(dpage)
            _click_and_wait(dpage, LIST_PROJECTS, "projectsOut")
            dpage.locator("button[data-act=list-projects]").scroll_into_view_if_needed()
            dpage.wait_for_timeout(200)
            dpage.screenshot(path=OUT_DIR / "dark-mode-overview.png", full_page=True)
            written["dark-mode-overview.png"] = "dark-scheme console"
            dctx.close()

            # ---- demo GIF frames (1024x640 @1x, silent) ------------------------
            # Narration order: console → project → pipeline → quality result →
            # provenance → export. Each data scene is shot IMMEDIATELY after the
            # action that produced it, so the frames show what the click really
            # caused (shooting all scenes after all clicks would show the export
            # output in the quality scene too — both target the same panel).
            gctx = browser.new_context(viewport={"width": 1024, "height": 640})
            gpage = gctx.new_page()
            gpage.goto(CONSOLE_URL.format(port=port), wait_until="networkidle")
            _wait_ready(gpage)
            _click_and_wait(gpage, LIST_PROJECTS, "projectsOut")
            _fill(gpage, "pid", project_id)
            _fill(gpage, "dspid", project_id)
            _fill(gpage, "expid", project_id)

            counter = {"i": 0}

            def _shoot(scenes: list[tuple[str, str]]) -> None:
                for _scene, sel in scenes:
                    gpage.locator(sel).scroll_into_view_if_needed()
                    gpage.wait_for_timeout(150)
                    for _ in range(5):  # 5 frames per scene; assembler dedupes
                        gpage.screenshot(path=frames_dir / f"frame-{counter['i']:03d}.png")
                        counter["i"] += 1

            _shoot(
                [
                    ("header", "section[aria-labelledby=auth-title]"),
                    ("projects", "section[aria-labelledby=proj-title]"),
                    ("pipeline", "section[aria-labelledby=pipe-title]"),
                ]
            )
            _click_and_wait(gpage, "validate", "dsOut")
            _shoot([("quality", "section[aria-labelledby=ds-title]")])
            _click_and_wait(gpage, "listExamples", "exOut")
            _fill(gpage, "reviewEx", review_candidate["id"])
            _click_and_wait(gpage, "viewLineage", "revOut")
            _shoot([("lineage", "section[aria-labelledby=ex-title]")])
            _click_and_wait(gpage, "export", "dsOut")
            _shoot([("export", "section[aria-labelledby=ds-title]")])

            written["offline-demo.gif"] = f"{counter['i']} frames in {frames_dir}"
            gctx.close()
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()

    state_out = {"written": written, "project_id": project_id, "port": port}
    (frames_dir / "capture-summary.json").write_text(json.dumps(state_out, indent=2))
    return state_out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8970)
    parser.add_argument(
        "--frames-dir",
        type=Path,
        default=None,
        help="Where GIF frames go (default: fresh temp dir).",
    )
    args = parser.parse_args()
    if not (args.workspace / "state.json").exists():
        raise SystemExit("workspace not prepared — run prepare_demo_state.py first")
    frames_dir = args.frames_dir or Path(tempfile.mkdtemp(prefix="knovaryn-frames-"))
    summary = capture(args.workspace, args.port, frames_dir)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
