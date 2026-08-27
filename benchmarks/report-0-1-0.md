# Knovaryn Benchmark Report 0.1.0

> **⚠️ HISTORICAL REPORT — superseded by [report-0-2-1.md](report-0-2-1.md).**
> This report measures the **old v0.1.0 framework** as it stood on 2026-08-13.
> It used a **deterministic fake provider**: it did **not** test live model
> quality, generation throughput, or cost, and makes no such claim.
> **It is not the current release benchmark.** Its bundle-size variation
> between runs is historical: v0.1.0 predated the release-reproducibility
> guarantee, so those values must **not** be read as current reproducibility
> evidence. Measured values below are preserved exactly as recorded.

- **Report ID / date:** knovaryn-bench-0.1.0 / 2026-08-13
- **Methodology:** inline v0.1.0-era methodology; superseded by the canonical
  [benchmark methodology](../docs/reference/benchmark-methodology.md) (v2)
- **Full reproducibility:** corpus manifest at `benchmarks/corpus/README.md`; runner at
  `benchmarks/bench_suite.py`; corpus bytes under `tests/fixtures/intake/`. No network, no keys.

> **What this report is and is not.** Everything below is a **framework** measurement
> (pipeline yield, lineage resolution, export compatibility, framework overhead) on the
> deterministic offline fake provider against the bundled synthetic text corpus. It is
> **not** synthetic-data-generation throughput on a real model, **not** a model-quality
> claim, and makes **no** claim that the produced data improves any downstream model or is
> bias-free. Category N3 / honest-claims rule.

## Environment

- **Hardware:** Apple M4 (10 cores), 16 GB RAM, integrated GPU, macOS 26.5.2 (build 25F84).
- **Software:** Python 3.13.7; Knovaryn 0.1.0 (source tree at `<repo>/src`); parser = markdown /
  plain-text intake for the text corpus (no `docling` extra in this run); chunker =
  `structure_aware`; provider = `FakeProvider` (deterministic, zero-cost).
- **Optional extras:** none used in this run. No Docling, no DocETL, no LiteLLM, no model.

## Corpus (text corpus, always available)

From `benchmarks/corpus/README.md` — all four files authored by the maintainers, licensed
Apache-2.0, synthetic (no third-party material):

| File | Format | SHA-256 (as recorded) |
|---|---|---|
| `numbered-headings.md` | Markdown (nested headings, lists) | `a8f2598c…b20` |
| `multilingual.txt` | Plain text (ASCII + U+00FC.. + CJK) | `415cb361…e9b8` |
| `sample.csv` | CSV | — |
| `sample.json` | JSON | — |

Total sources ingested: **4**. Byte sizes are the committed fixture bytes (fixed by the
committed files); the recorded SHA-256 pins each file's bytes.

> Category table/layout extraction (the PDF corpus under `benchmarks/corpus/README.md`) is
> **not** measured in this run — it requires the `docling` extra. See the corpus README.

## Config

- **Profile:** offline deterministic (`fake` provider).
- **Chunker:** `structure_aware` (Knovaryn default).
- **Plan:** factual_explanation 0.5 / procedure 0.3 / comparison 0.2; difficulty basic 0.3 /
  intermediate 0.5 / advanced 0.2; `maximum_dataset_size` 2000.
- **Split/seed:** deterministic fake provider; no randomness in this run.
- **Human-review sample:** n/a (fake provider, deterministic).

## Runs

Each run invokes `benchmarks/bench_suite.py` end-to-end (parse → chunk → span → candidate →
generate → validate → version → export all formats). 3 repetitions reported.

| Metric | Run 1 | Run 2 | Run 3 | Median |
|---|---|---|---|---|
| Sources / parsed | 4 / 4 | 4 / 4 | 4 / 4 | 4 / 4 |
| Parse success rate | 1.0 | 1.0 | 1.0 | **1.0** |
| Chunks / spans | 6 / 6 | 6 / 6 | 6 / 6 | 6 / 6 |
| Chunk heading coverage | 0.5 | 0.5 | 0.5 | **0.5** |
| Candidates / examples | 3 / 2 | 3 / 2 | 3 / 2 | 3 / 2 |
| Accepted examples | 2 | 2 | 2 | **2** |
| Quarantined | 0 | 0 | 0 | 0 |
| Lineage resolution rate | 1.0 | 1.0 | 1.0 | **1.0** |
| Elapsed (s) | 0.1246 | 0.1195 | 0.1221 | **0.1221** |
| Examples / second (framework overhead only, N3) | 16.05 | 16.74 | 16.38 | **16.38** |
| Peak allocated (bytes) | 1,559,392 | 1,558,536 | 1,558,722 | **1,558,722** |
| Release bundle bytes | 2,921 | 2,922 | 2,922 | **2,922** |
| Detached release sha256 present | ✓ | ✓ | ✓ | ✓ |

### Export compatibility (all formats round-trip, lineage resolvable, digest present)

Every export in the previous run's `export_status` was `ok` — each produced >0 rows, non-empty
bytes, and a sha256 digest with resolvable lineage. Formats: `alpaca`, `evaluation`,
`huggingface_layout`, `kto`, `openai_chat`, `sharegpt`, `trl_preference`, `trl_sft`.

### Quality gate outcomes

- Grounding-validator reject count: **0** (all candidates passed groundedness on the
  deterministic corpus).
- Duplicate rejects: **0**; contamination rejects: **0** on this tiny corpus (dedupe/leakage
  machinery exercised, nothing to reject at this scale).

## Errors / outliers

- Job states: all succeeded; no retries, no checkpoints, no cancelled or partial jobs.
- No outliers: the corpus is tiny and deterministic, so run-to-run variance is sub-millisecond
  and driven by framework overhead only.
- One observed cross-run variance in release-bundle byte size (2,921 vs 2,922) reflects map/
  ordering of manifest fields across runs — deterministic per identical code path; reproducible
  zip mode (`reproducible=True`) is exercised in `tests/test_release_integrity.py`.

## Interpretation (honest)

- **What it shows:** the offline framework parses all text sources, resolves every accepted
  example's provenance/lineage to pipeline entities, gates generated candidates (groundedness
  clean on this corpus), dedupes without false rejects, and round-trips all 8 export formats
  with resolvable lineage + digest. Release bundles carry a detached checksum.
- **What it does not show:** this is **not** a generative-throughput or model-quality
  benchmark. `examples_per_second` here measures **framework overhead only** on a 4-document
  synthetic corpus with a zero-cost fake provider — it must **not** be read as synthetic-data
  generation speed on a real model, and it does **not** scale to larger corpora without a
  re-run. No model improvement, bias, or hallucination claim is made.
- **Limitations:** table/layout parsing fidelity (PDFs, scanned, two-column, docx/xlsx) is
  intentionally **not** measured here (requires the `docling` extra); cost per accepted example
  and live-provider yield require credentials and are out of scope for this offline run.
