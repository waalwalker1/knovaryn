---
description: >-
  Accessibility standards for every Knovaryn surface: contrast
  floors, focus visibility, keyboard paths, reduced-motion
  handling, and alt-text rules.
---

# Accessibility

Knovaryn's documentation targets **WCAG 2.x AA** on every public surface.
These are the expectations each surface is verified against (browser and
axe-core verification runs in the release checks):

## Perception

- **Text contrast** ≥ 4.5:1 body, ≥ 3:1 large text — pairings pre-approved
  in [color](color.md#contrast-rules); new pairings get checked before merge.
- **Non-text contrast** ≥ 3:1 for state borders, focus rings, chart marks.
- **Descriptive alt text**: images state their content and purpose
  ("Pipeline diagram: sources flow through chunking and quality gates into
  export"), not "image of".
- **Screen-reader text for complex diagrams**: every architecture or
  pipeline graphic has a text equivalent per
  [diagrams](diagrams-and-data-visualization.md#text-equivalents).
- **Static alternatives for interactive graphics**: the interactive
  pipeline/architecture explorers render a complete static figure without
  JavaScript; interaction adds detail, it never gates content.

## Operation

- **Visible focus** everywhere: `--kn-focus-ring` (2-color ring) on all
  interactive elements; never `outline: none` without a replacement.
- **Keyboard navigation**: menus, tabs, accordions, and the theme drawer
  work without a pointer; no keyboard traps; skip-to-content provided by
  the theme.
- **Logical tab order** follows visual/reading order.
- **Touch-target size** ≥ 44 × 44 px including padding
  ([spacing](spacing-and-layout.md#touch-targets)).
- **200% zoom**: layouts reflow to one column without loss of content or
  function; no horizontal page overflow at 320 px width either.
- **Code blocks on mobile**: horizontally scrollable inside their own
  container with visible affordance; copy buttons remain reachable.

## Understanding

- **Heading hierarchy** starts at one `h1` per page and skips no levels.
- **Landmarks**: header/nav/main/footer from the theme; page content in
  `main`.
- **Accessible names** on all controls ("Copy command", "Switch to dark
  mode"), not icon-only silence.
- **No color-only meaning**: status uses color + label + shape/icon;
  links in prose are underlined.
- **Reduced-motion behavior**: all animation collapses under
  `prefers-reduced-motion` ([motion](motion.md)); nothing blinks, auto-
  plays, or parallax-scrolls.

## Robustness

- Pages are usable with JavaScript disabled (static fallbacks).
- Forms and search keep native semantics; custom widgets use correct
  roles/states.
- Language is declared (`lang="en"`); abbreviations expand on first use.

## Verification, not aspiration

The browser verification pass walks real journeys (read docs, run quickstart,
find benchmark evidence) at mobile/desktop widths, in both schemes, with
keyboard only, and with axe-core scanning — results recorded as release
evidence. A regression found there is a release blocker, same tier as a
failing test.
