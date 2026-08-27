---
description: >-
  The Knovaryn palette: light/dark tokens, trace/paper/ink
  semantics, contrast ratios per pairing, and how accent colors
  map to status states.
---

# Color

Authoritative values live in
[`docs/assets/design-system/tokens.css`](../assets/design-system/tokens.css)
(`--kn-*` custom properties). This page documents them and the rules for
using them.

## Brand colors

| Token | Light | Dark | Role |
|---|---|---|---|
| `--kn-color-brand-primary` | `#0E7C6B` **Trace** | `#2EB39A` | Provenance route, verification, links, primary actions |
| `--kn-color-brand-secondary` | `#1C2B33` **Ink** | `#1C2B33` | Structure, text, monochrome marks |
| `--kn-color-accent` | `#2EB39A` | `#3FD0B4` | Highlights, focus, active states — sparingly |

Trace is the identity color. It appears wherever data provenance or verified
quality is being expressed. Ink is the structural neutral. The accent exists
for dark-scheme emphasis; it is never a second brand hue.

## Surfaces and text

| Token | Light | Dark | Role |
|---|---|---|---|
| `--kn-color-surface` | `#FBFAF7` Paper | `#0F1B21` Ink-deep | Page ground |
| `--kn-color-surface-elevated` | `#FFFFFF` | `#16242C` | Cards, panels |
| `--kn-color-surface-sunken` | `#F1EFE8` | `#0A1318` | Wells, code blocks, insets |
| `--kn-color-text-primary` | `#1C2B33` | `#ECF2EF` | Body text |
| `--kn-color-text-secondary` | `#4C5B61` | `#A9BFBB` | Captions, metadata |
| `--kn-color-text-disabled` | `#909EA6` | `#6F7E87` | Disabled only |
| `--kn-color-border` | `#D3DADD` | `#24363F` | Hairlines, card edges |
| `--kn-color-border-strong` | `#909EA6` | `#55636C` | Emphasized edges, inputs |
| `--kn-color-link` | `#0B6B5D` | `#2EB39A` | Hyperlink text |

## Neutral scale

A cool slate ramp aligned to Ink (`--kn-gray-900` equals Ink). Use for charts,
dividers, and any step between surface and text. Dark scheme inverts the ramp.

| Step | Light | Dark |
|---|---|---|
| `--kn-gray-0` | `#FFFFFF` | `#0F1B21` |
| `--kn-gray-50` | `#F5F7F7` | `#16242C` |
| `--kn-gray-100` | `#E8ECED` | `#1D2E37` |
| `--kn-gray-200` | `#D3DADD` | `#24363F` |
| `--kn-gray-300` | `#B4BFC4` | `#31454F` |
| `--kn-gray-400` | `#909EA6` | `#4C626C` |
| `--kn-gray-500` | `#6F7E87` | `#6F838D` |
| `--kn-gray-600` | `#55636C` | `#94A7AE` |
| `--kn-gray-700` | `#404D55` | `#B4C5CA` |
| `--kn-gray-800` | `#2C3A42` | `#CFDDE0` |
| `--kn-gray-900` | `#1C2B33` | `#ECF2EF` |

## Semantic status

| Token | Light | Dark | Meaning |
|---|---|---|---|
| `--kn-color-success` | `#0E7C6B` | `#2EB39A` | Verified / accepted / passed a gate (= brand Trace) |
| `--kn-color-warning` | `#B45309` Signal amber | `#D97706` | Review / quarantine / needs human decision |
| `--kn-color-error` | `#B3261E` | `#FF8A80` | Rejected / failed gate / refusal |
| `--kn-color-info` | `#404D55` | `#A9BFBB` | Neutral status, metadata |

Status color is **never the only carrier of meaning**: every status also has
a text label and/or icon (see [accessibility](accessibility.md)). In product
UIs amber maps to the *review* state, success to *accepted*, error to
*rejected/quarantined* — matching the pipeline's real outcome vocabulary.

## Contrast rules

All pairings below are WCAG 2.x AA-checked against their own scheme:

- body text ≥ **4.5:1** on its surface (both schemes' text-primary ≈ 12–15:1,
  text-secondary ≥ 4.5:1);
- large display text (≥ 24 px bold) ≥ **3:1**;
- non-text UI (borders conveying state, focus rings) ≥ **3:1** against
  adjacent colors;
- links keep ≥ 4.5:1 and are underlined in running prose;
- never place Trace text on Amber, Amber on Trace, or any status color on
  another status color.

If a proposed pairing fails, change the pairing — not the threshold.
