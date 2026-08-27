---
description: >-
  Iconography and illustration rules: stroke weight, grid,
  metaphor vocabulary, license-clean sources, and when not to
  illustrate at all.
---

# Icons and illustrations

## Icon style

- **Grid:** 24 × 24 px, 1.75 px monoline stroke (2 px at 24 px is acceptable
  for theme-bundled icons), round caps and joins — matching the Tracemark's
  construction.
- **Geometry:** straight segments and circular arcs only; the provenance
  motifs (segmented span, gate ring, solid stroke) are preferred metaphors.
- **Fill:** icons are stroked, not filled; the only fills are status dots
  and the gate core.
- **Source:** documentation uses the theme's locally bundled icon set
  (Material Design Icons) — no icon CDN, no third-party requests. Custom
  icons are generated SVG in this style under `docs/assets/`.
- **Sizing:** 16/20/24 px UI sizes; below 16 px use the symbol tile instead
  of redrawing the mark.

Every icon that carries meaning gets an accessible name; decorative icons
are hidden from assistive technology ([accessibility](accessibility.md)).

## Illustration style

Illustrations explain mechanics — they are diagrams with atmosphere, not
decoration:

- Monoline scenes built from the pipeline vocabulary: a document spine,
  segmented spans traveling toward a gate, a solid verified stroke leaving
  it.
- One accent color per scene (Trace), structure in Ink/neutrals, surfaces
  from the scheme palette; no gradients inside strokes, no shadows inside
  illustrations.
- No mascots, no robots-with-faces, no stock art, no screenshots-of-code as
  illustration.
- Scenes render from generators where practical (same discipline as brand
  assets) so light/dark variants stay in sync.
