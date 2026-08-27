---
description: >-
  The Knovaryn design system overview: visual voice, token files,
  component classes, and the process that keeps README, docs, and
  diagrams consistent.
title: "Design system"
---

# Knovaryn design system

The design system keeps every Knovaryn surface — README, documentation site,
diagrams, screenshots — saying the same thing in the same visual voice.

The voice follows the brand's one sentence: **every training example, traced
to its source.** Visuals show provenance routes (segmented evidence), quality
gates (the ring), and verified output (solid strokes). Nothing decorative
outranks clarity.

## What lives here

| Page | Contents |
|---|---|
| [Brand foundations](brand-foundations.md) | Identity attributes, logo system, voice |
| [Color](color.md) | Palettes, neutral scale, semantic status, contrast rules |
| [Typography](typography.md) | Typefaces, type scale, usage |
| [Spacing and layout](spacing-and-layout.md) | Grid, spacing scale, content widths, breakpoints |
| [Components](components.md) | The shared component vocabulary |
| [Icons and illustrations](icons-and-illustrations.md) | Icon style, illustration rules |
| [Diagrams and data visualization](diagrams-and-data-visualization.md) | Diagram grammar, chart style, benchmark graphics |
| [Accessibility](accessibility.md) | WCAG AA expectations per surface |
| [Motion](motion.md) | Durations, easing, reduced-motion contract |

## Where tokens are defined

Machine-readable tokens live in
[`docs/assets/design-system/tokens.css`](../assets/design-system/tokens.css)
as CSS custom properties (`--kn-*`) and are loaded by the site through
`mkdocs.yml`'s `extra_css`. The documentation pages describe those tokens;
when a value changes, change the CSS file and the page together.

## Who consumes it

- **Contributors** writing or editing docs pages, diagrams, or console output.
- **Generators**: everything under `scripts/visuals/` reads these values so
  brand assets stay reproducible (see
  [brand foundations](brand-foundations.md#reproduction)).
- **Reviewers** checking a proposal against
  [accessibility](accessibility.md) before merge.

## Ground rules

1. **Truth first** — no visual may imply a claim the
   [claim matrix](../reference/claim-matrix.md) does not back.
2. **Provenance is the motif** — segmented spans, gates, solid verified
   strokes; not clouds, robots, or magic sparkles.
3. **Contrast over aesthetics** — if a color pairing fails WCAG AA, the
   pairing is wrong (see [color](color.md#contrast-rules)).
4. **Static fallbacks exist** — anything interactive degrades to a readable
   static equivalent ([motion](motion.md), [accessibility](accessibility.md)).
5. **No invented numbers** — charts carry real values from committed
   benchmark runs with their context labels
   ([data visualization](diagrams-and-data-visualization.md)).
