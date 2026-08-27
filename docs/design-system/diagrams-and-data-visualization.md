---
description: >-
  Diagram standards: node/stroke semantics for provenance routes,
  quality rings, and verified outputs, plus chart styling and
  colorblind-safe defaults.
---

# Diagrams and data visualization

## Diagram grammar

All architecture and pipeline diagrams share one grammar:

| Element | Drawing |
|---|---|
| Source document | Solid rectangle — the spine of truth |
| Chunk / span | Segmented rounded stroke (the evidence motif) |
| Quality gate | Ring with contrasting core (nothing passes by accident) |
| Verified artifact | Single solid stroke or rectangle in Trace |
| Store / database | Cylinder, hairline border |
| External service | Dashed border, labeled with its real name |
| Flow | Directional arrow, labeled with the artifact that moves |

Rules:

- Monoline strokes on a consistent width scale; round caps/joins; no
  gradients, no 3-D, no skeuomorphism.
- Colors from the scheme palettes only: structure Ink/neutrals, verification
  Trace, review Amber. Max two accents per diagram.
- Labels in the body typeface at caption/secondary size; node names match
  the product's real vocabulary (`ProjectService`, `JobEngine`, `ArtifactStore`).
- Every diagram ships as a committed source (`.mmd` or generator script)
  plus its rendered raster, with a text equivalent next to it
  ([accessibility](accessibility.md)).
- Diagrams never show data flows that don't exist (no "cloud sync", no
  implied telemetry).

## Chart style

For benchmark and metric charts:

- **Categorical order:** Trace → Ink → Signal amber → gray-400 → accent;
  repeat by lightness, never by new hues.
- **Rates** carry Wilson 95% interval whiskers in Ink; the interval is part
  of the mark, not an appendix.
- **Axes:** hairline `--kn-color-border`, labels at secondary size, units
  stated ("ms", "examples/s"); start bar axes at zero.
- **Gridlines:** minimal horizontal only, gray-100.
- **Legend:** explicit, ordered as the data; direct labeling preferred when
  series count ≤ 3.
- Numbers render exactly as measured — no smoothing, no truncated axes that
  exaggerate differences.

### Benchmark graphics

Any performance graphic must carry the context label from the canonical
[methodology](../reference/benchmark-methodology.md):

> *Offline deterministic framework benchmark — not live-model generation
> throughput.*

and must state: what ran (command), how many repetitions, which release.
A benchmark graphic without its context label does not ship.

## Text equivalents

Each diagram/chart gets either a structured text alternative (list of nodes
and edges, or a table of the plotted values) or a caption that conveys the
same conclusion plus a link to the underlying data files. Decorative
redundancy is fine; missing equivalents are not.
