---
description: >-
  Component inventory of the Knovaryn surfaces: cards, callouts,
  tabs, tables, code blocks — usage, dos/don'ts, and accessibility
  notes.
---

# Components

The shared vocabulary for Knovaryn surfaces. Implementation classes consume
the tokens in `docs/assets/design-system/tokens.css` (site CSS lands with the
Pages redesign); this page fixes the contract each component must honor.
Every component works in light and dark scheme, at 200% zoom, and from the
keyboard.

## Hero sections

- One `--kn-text-display(-lg)` sentence; optional eyebrow overline
  (`--kn-text-caption`, uppercase, tracked).
- At most two actions ([primary/secondary actions](#primary-and-secondary-actions)).
- Optional media frame (`--kn-radius-lg`, `--kn-shadow-card`) holding a
  screenshot or diagram — never a stock photo.
- Padding `--kn-space-8` vertical on desktop, `--kn-space-6` below 640 px.

## Primary and secondary actions

- **Primary:** solid Trace fill, Paper text, `--kn-radius-sm`; one per view.
- **Secondary:** transparent fill, `--kn-border-width-strong` border in
  `--kn-color-border-strong`, text-primary label.
- Both: minimum hit area 44 × 44 px, visible focus ring
  (`--kn-focus-ring`), disabled state uses `--kn-color-text-disabled`.
- Labels are verb phrases: "Run the offline demo", "Read the quickstart".

## Command blocks

- Sunken surface (`--kn-color-surface-sunken`), mono stack,
  `--kn-radius-sm`.
- A copy affordance with an accessible name ("Copy command"); copied state
  announces itself to screen readers.
- Commands must be pasteable as-is: real flags, no pseudo-syntax, and any
  required environment variable shown on its own line above.
- Output blocks are visually distinct from input (muted prompt symbol vs
  none).

## Callouts

| Kind | Border/accent | Use |
|---|---|---|
| Note | Info | Supplementary context |
| Tip | Trace | Practical shortcuts |
| Warning | Amber | Decisions with consequences (costs, licenses) |
| Danger/Error | Error color | Security-relevant refusal behavior |

Icon + colored left edge **and** a text label ("Warning") — color is never
the only signal. Body stays at body size.

## Feature cards

- Elevated surface, `--kn-radius-md`, `--kn-shadow-card`,
  padding `--kn-space-3`.
- Icon or mini-diagram (24 px grid), title at heading weight, ≤ 2 lines of
  body at secondary size, optional "Learn more" link.
- Equal height in rows; no fake metrics inside cards.

## Maturity labels

Pill shape (`--kn-radius-pill`), caption size, uppercase text plus dot:

| Label | Color | Meaning source |
|---|---|---|
| STABLE | Trace dot | [Claim matrix](../reference/claim-matrix.md) |
| ALPHA | Amber dot | Claim matrix |
| EXPERIMENTAL | Gray outline | Claim matrix |
| OPTIONAL | Gray outline | Requires an extra / external service |
| OWNER ACTION | Amber outline | External step a maintainer must perform |

The pill always links to (or sits beside) its claim-matrix row context.

## Trust/evidence cards

State a claim, then its evidence: benchmark number + link to the committed
report and methodology; test result + link to the suite; maturity + claim
matrix row. Evidence cards never round numbers upward ("3 runs", "82%
coverage" appear exactly as measured) and carry their context labels
([data visualization](diagrams-and-data-visualization.md)).

## Tabs and accordions

- Tabs switch peer content (e.g., install per OS); accordions hold
  optional depth (advanced flags, troubleshooting).
- Keyboard: tabs arrow-navigable with visible focus; accordion headers are
  buttons with expanded/collapsed state announced.
- Content inside tabs is indexed by the site search; critical paths
  (install) default to the most common case open, not everything collapsed.

## Architecture panels

Framed containers for system diagrams: sunken background, strong border,
caption slot underneath citing the diagram's source file. Diagrams follow
the [diagram grammar](diagrams-and-data-visualization.md).

## Provenance nodes

The recurring motif for lineage views: document = solid rectangle (spine),
chunk/span = segmented rounded strokes, gate = ring with contrasting core,
verified example = solid stroke leaving the gate. Nodes connect with
directional arrows labeled by artifact type. Every provenance graphic has a
text equivalent ([accessibility](accessibility.md)).

## Quality-gate states

| State | Visual |
|---|---|
| Accepted | Trace check + "accepted" label |
| Review | Amber diamond + "review" label |
| Quarantined | Amber outlined box + reason code |
| Rejected | Error cross + machine-readable reason code |

Reason codes render in mono next to the state label — they are part of the
product's public vocabulary.

## Code/output comparisons

Side-by-side "without / with" or "command / result" pairs share one frame
with a labeled divider; on mobile they stack with the same labels. Never
imply output that wasn't produced by the shown command.

## Metric cards

One number, one label, one evidence link. Numbers come from committed
benchmark results; rates carry their Wilson interval; counts carry their n.
Context label mandatory for performance figures
([data visualization](diagrams-and-data-visualization.md#benchmark-graphics)).

## Screenshots and captions

Screenshots live in `docs/assets/screenshots/`, framed with
`--kn-radius-md` and a hairline border so light UI shots read on dark
scheme. Captions sit below at secondary size, full sentences ending in a
period, describing what the reader should notice.

## Previous/next navigation

Theme-provided prev/next links keep their accessible names ("Next »"
expanded to page title via theme config); never removed on key guides.

## Mobile navigation

Theme drawer below 1024 px; the drawer preserves group order from `nav`,
focus moves into it on open and returns on close (verified in browser tests).

## Footer

Version string (authoritative `__version__`), license note, repository and
PyPI links, privacy statement linking the analytics policy. No badge walls,
no tracker pixels.

## Warning and limitation notices

Limitations get the same typographic care as features: a limitations block
uses the callout pattern with honest prose ("not measured", "alpha"),
linking the evidence or methodology that explains why the limit exists.
