---
description: >-
  Typography: system font stacks (no webfonts), type scale,
  reading rhythm, code-face treatment, and multilingual fallbacks.
---

# Typography

## Typefaces

| Token | Stack | Use |
|---|---|---|
| `--kn-font-body` | `system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif` | All prose and UI |
| `--kn-font-display` | = body stack | Heroes, display sizes |
| `--kn-font-mono` | `ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace` | Commands, code, IDs, checksums |

The site loads **no webfonts**. System stacks keep the documentation
network-free (privacy policy: no third-party requests from docs or README),
identical across mirrors, and fast on cold caches. The Knovaryn *logo* is
exempt: its letterforms are original vector paths
([brand foundations](brand-foundations.md)), not a font.

## Type scale

Ratio 1.25 over a 16 px body (`--kn-text-scale-ratio`). Sizes are tokens in
`tokens.css`.

| Token | Size | Line height | Use |
|---|---|---|---|
| `--kn-text-display-lg` | 44 px | 1.15 (`--kn-leading-tight`) | Landing hero only |
| `--kn-text-display` | 32 px | 1.15 | Page heroes |
| `--kn-text-title` | 24 px | 1.35 (`--kn-leading-snug`) | Section titles (`##`) |
| `--kn-text-heading` | 20 px | 1.35 | Subsections (`###`) |
| `--kn-text-body` | 16 px | 1.6 (`--kn-leading-body`) | Body copy |
| `--kn-text-secondary-size` | 14 px | 1.5 | Captions, table metadata |
| `--kn-text-caption` | 12 px | 1.4 | Overlines, footnotes |

Weights: **400** body, **500** emphasis/UI labels, **700** display and
headings. Avoid weights above 700 — the identity is machined, not heavy.

## Usage rules

- One `display` size per page; heroes are single-sentence.
- Headings skip no levels ([accessibility](accessibility.md)).
- Overlines are uppercase with `letter-spacing: 0.08em`
  (`--kn-tracking-overline`) at caption size — used for eyebrow labels like
  `BENCHMARK` or `MCP SURFACE`.
- Code always renders in the mono stack at ≤ 0.9em inline so it sits optically
  centered in prose.
- Long commands wrap on explicit `\` continuations, never mid-token;
  code blocks scroll horizontally inside their own container and never widen
  the page.
- Numbers in tables and metrics use tabular alignment where available
  (`font-variant-numeric: tabular-nums`).
