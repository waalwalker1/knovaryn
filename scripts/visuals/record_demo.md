# Recording the offline demo (`offline-demo.gif`)

How `docs/assets/screenshots/offline-demo.gif` is produced, what it shows, and
how to re-record it. Every frame comes from the real web console driven by
Playwright against the deterministic demo workspace — nothing is mocked.

## The narration (24 s, silent, no flashing)

| Scene | Seconds | What the viewer sees |
| ----- | ------- | -------------------- |
| Console | 0–4 | Header with the live health status (`server healthy · local mode`) and the token section |
| Projects | 4–8 | The demo project listed with its real id, slug, license-ready metadata |
| Pipeline | 8–12 | Profile / budget / target controls — the run is queued from here |
| Quality result | 12–16 | The real quality report: 6/6 accepted (5 sft + 1 kto), per-topology counts |
| Provenance | 16–20 | One example's lineage: source document → span id → precision |
| Export | 20–24 | The export result: byte size, line count, sha256 checksum |

Pacing disclosure: frames are held for ~800 ms (5 shots per scene); the console
itself responds in well under a second — the GIF is *slower* than reality, not
sped up.

## Reproduce it

```bash
# 1. deterministic workspace (offline fake provider, synthetic Apache-2.0 sources)
uv run --no-sync python scripts/visuals/prepare_demo_state.py --workspace /tmp/knovaryn-visual-demo

# 2. capture the console states (writes docs/assets/screenshots/*.png and /tmp/knovaryn-frames/)
uv run --no-sync python scripts/visuals/capture_docs_screenshots.py \
    --workspace /tmp/knovaryn-visual-demo --frames-dir /tmp/knovaryn-frames

# 3. assemble + optimize the GIF and poster
uv run --no-sync python scripts/visuals/optimize_assets.py --frames-dir /tmp/knovaryn-frames
```

The README embeds the same `offline-demo.gif` (linked, not autoplayed) plus
the canonical §13.2 section crops (`provenance-lineage.png`,
`quality-gates.png`, `export-release.png`) captured in step 2 — there are no
separate README variants to keep in sync.

## Accessibility contract (§13.4)

- **Silent by default** — no audio track exists.
- **No flashing** — 6 scenes × ~4 s, hard cuts only, no strobe content.
- **Reduced motion** — GitHub autoplays GIFs and offers no `prefers-reduced-motion`
  pause, so the README presents the GIF as a *linked* image: readers who avoid
  motion can skip it and read the static screenshots plus the transcript below,
  which cover 100% of the shown information. The docs site embeds the GIF behind
  a static poster (`offline-demo-poster.png`) with the same transcript.
- **Transcript** — the scene table above is the authoritative description; the
  figure caption in the README names each stage in one line.

## Privacy (§13.3)

Frames contain only the synthetic `visual-demo` workspace: no local usernames,
no absolute home paths, no emails, no tokens, no browser chrome, no unrelated
applications. `scripts/check_visual_assets.py` (§15) enforces the privacy
patterns on every captured asset.
