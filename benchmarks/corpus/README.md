# Knovaryn benchmark corpus (spec WP N2)

Every benchmark runs on a **fixed, versioned corpus** whose origin and license are
recorded here. We use only documents we are permitted to redistribute. The
bundled corpus is intentionally small and synthetic so that benchmarks are
**deterministic and reproducible** without external downloads — it exercises
varied formats, layouts, and encodings, not scale.

## Provenance & licensing policy

- **Synthetic test fixtures** (below) were authored for this repository. They are
  original work by the Knovaryn maintainers and are licensed **Apache-2.0**
  (same as the codebase), with no third-party source material.
- No proprietary, confidential, or non-redistributable document is used.
- Each file's **SHA-256** is recorded so a benchmark run can be pinned to the
  exact bytes that produced its numbers.
- Formats/layouts requiring the optional `docling` / `docetl` / `ml` extras are
  marked; the **always-available text corpus** runs with no extras and no
  network.

## Text / markup corpus (always available)

These run in every offline benchmark with no optional extras.

| File | Format | Source | License | SHA-256 |
|---|---|---|---|---|
| `numbered-headings.md` | Markdown (nested headings, list/ordered) | Synthetic (this repo) | Apache-2.0 | `a8f2598c…b20` |
| `multilingual.txt` | Plain text (ASCII + U+00FC.. + CJK Unicode) | Synthetic (this repo) | Apache-2.0 | `415cb361…e9b8` |
| `sample.csv` | CSV (header + 2 rows) | Synthetic (this repo) | Apache-2.0 | — |
| `sample.json` | JSON (`{a,b}`) | Synthetic (this repo) | Apache-2.0 | — |

## Document corpus (requires `docling` extra)

These PDFs/docx/xlsx exercise layout diversity (native text, scanned, two-column,
large page count, password-protected, merged cells). Parsing fidelity on these is
measured **only when the `docling` extra is installed**; the benchmark report
states explicitly when a metric is gated on that extra.

| File | Format | Layout under test | Source | License |
|---|---|---|---|---|
| `native-text.pdf` | PDF | extractable native text | Synthetic (this repo) | Apache-2.0 |
| `scanned.pdf` | PDF | scanned / no text layer (OCR path) | Synthetic (this repo) | Apache-2.0 |
| `two-column.pdf` | PDF | multi-column layout | Synthetic (this repo) | Apache-2.0 |
| `huge-pages.pdf` | PDF | large page count (resource guard) | Synthetic (this repo) | Apache-2.0 |
| `password-protected.pdf` | PDF | encrypted (should be refused) | Synthetic (this repo) | Apache-2.0 |
| `malformed.pdf` | PDF | malformed header (should be refused) | Synthetic (this repo) | Apache-2.0 |
| `docx-list.docx` | DOCX | lists | Synthetic (this repo) | Apache-2.0 |
| `merged-cells.xlsx` | XLSX | merged cells | Synthetic (this repo) | Apache-2.0 |

## Reproducibility

- Corpus is committed to the repo under `tests/fixtures/intake/` — the bytes are
  fixed by the recorded SHA-256.
- Benchmark commands, environment, and interpretation rules: see
  `docs/marketing/benchmark-methodology.md`.
- Deterministic seed + fake provider: see `benchmarks/bench_suite.py`.
