---
description: >-
  Motion principles: duration tokens, easing, hover/focus
  choreography, reduced-motion collapse, and the infinite-loop ban
  enforced in CI.
---

# Motion

Motion in Knovaryn surfaces confirms cause and effect — it never performs.

## Durations and easing

| Token | Value | Use |
|---|---|---|
| `--kn-dur-fast` | 120 ms | Hovers, focus, small state flips |
| `--kn-dur-base` | 180 ms | Reveals, tab/accordion transitions |
| `--kn-dur-slow` | 280 ms | Large panel transitions, page-level changes |
| `--kn-ease-out-soft` | `cubic-bezier(0.2, 0, 0, 1)` | Entrances, most transitions |
| `--kn-ease-inout-soft` | `cubic-bezier(0.4, 0, 0.2, 1)` | Moves between two stable states |

Nothing animates longer than 280 ms. Nothing loops except explicit,
user-initiated progress indicators (spinner during a real load).

## Rules

1. **M1 — Purposeful only.** Each animation answers "what just changed?".
   No ambient motion, no parallax, no decorative floating.
2. **M2 — Transform cheap properties.** Animate `opacity`/`transform`
   only; layout-triggering animations are defects.
3. **M3 — Interruptible.** A transition cut short by user input lands in
   its final state instantly; no queued or chained sequences.
4. **M4 — State is never hidden behind motion** — if JavaScript fails or
   animation is disabled, every element remains visible and readable.
5. **M5 — Reduced-motion contract:** under `prefers-reduced-motion: reduce`
   all durations collapse to ~0 (enforced globally in `tokens.css`).
   Interactive explorers additionally disable auto-stepping and provide
   manual controls.
6. **M6 — Static fallbacks:** the interactive pipeline/architecture
   explorers ship a complete static rendering; progressive enhancement
   adds stepping/highlighting on top ([accessibility](accessibility.md)).

## Where motion appears

- Theme defaults (navigation instant, content copy feedback) stay within
  these tokens.
- The pipeline explorer's stage highlighting uses `--kn-dur-base` +
  `--kn-ease-out-soft`; its autoplay mode is off by default and pauses on
  focus/hover.
- Benchmark charts never animate their data in; numbers appear with the
  chart.

## Governance

Motion regressions (new durations, looping effects) fail the visual-asset
check the same way off-token colors do — the check reads `tokens.css` as the
allowlist.
