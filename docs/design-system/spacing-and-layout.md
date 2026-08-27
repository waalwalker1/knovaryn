---
description: >-
  Spacing and layout tokens: scale, page grid, article measure,
  breakpoint behavior, and embedded-media sizing rules.
---

# Spacing and layout

## Spacing scale

A 4 px base grid; only these steps exist (`--kn-space-*` in `tokens.css`).

| Token | Value | Typical use |
|---|---|---|
| `--kn-space-1` | 4 px | Icon-to-label, inline gaps |
| `--kn-space-2` | 8 px | Inside components (chip padding, list rows) |
| `--kn-space-3` | 16 px | Component padding, card interiors |
| `--kn-space-4` | 24 px | Between sibling cards, grid gutter (`--kn-gutter`) |
| `--kn-space-5` | 32 px | Around callouts, between grouped blocks |
| `--kn-space-6` | 48 px | Section padding (compact) |
| `--kn-space-7` | 64 px | Section padding |
| `--kn-space-8` | 96 px | Hero top/bottom |

Never invent intermediate values (no 10 px, no 20 px). If a layout looks
wrong at these steps, the hierarchy is wrong — fix the hierarchy.

## Content widths

| Token | Value | Use |
|---|---|---|
| `--kn-content-max` | 76 rem (1216 px) | Full layout width for heroes, grids |
| `--kn-prose-max` | 46 rem (736 px) | Reading measure for prose (~80 characters) |

Prose columns never exceed the reading measure; wide content (tables,
diagrams, code) may use the full layout width inside its own horizontally
scrollable container.

## Grid behavior

- **12-column fluid grid**, gutter `--kn-gutter` (24 px), max width
  `--kn-content-max`, centered.
- Feature/metric cards: 3 columns ≥ 1024 px, 2 columns ≥ 640 px, 1 column
  below.
- Cards in a row stretch to equal height; their action areas align to the
  bottom.
- Breakpoints: **640 px** and **1024 px**. Navigation collapses per the
  theme's own behavior ([components](components.md#mobile-navigation)).

## Borders, radii, elevation

| Token | Value | Use |
|---|---|---|
| `--kn-border-width` | 1 px | Default hairlines |
| `--kn-border-width-strong` | 2 px | Emphasized edges, selected states |
| `--kn-radius-sm` | 6 px | Chips, inputs, inline code |
| `--kn-radius-md` | 12 px | Cards, panels, screenshots |
| `--kn-radius-lg` | 20 px | Hero panels, large media frames |
| `--kn-radius-pill` | 999 px | Maturity labels, status pills |
| `--kn-shadow-card` | layered soft | Resting cards |
| `--kn-shadow-elevated` | layered stronger | Hover/overlay surfaces |

Elevation is quiet: shadows suggest one lift level, not depth theatrics.
Borders carry most structure; on dark scheme borders do more work than
shadows.

## Touch targets

Interactive elements present a hit area of at least **44 × 44 px**
([accessibility](accessibility.md)); small visible controls get padded
transparent hit areas rather than larger artwork.
