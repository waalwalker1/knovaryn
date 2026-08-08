# Knovaryn — Benchmark Report: Template & Methodology

**Status:** Template + methodology. Reports generated against it are published in `benchmarks/` (or linked from the release). **A report is a claim about a corpus and environment; it must not over-claim.** Fill in every field; leave nothing implied.

---

## 1. Purpose and scope

A Knovaryn benchmark answers a specific question for an applied-LLM team:

> Given a permitted corpus and a fixed generation plan, how many *accepted* examples result, how many are duplicates, and what does each accepted example cost — under Knovaryn's structure-aware chunking compared with fixed-character chunks and with the DocETL gather profile?

It is **not** a claim that the resulting dataset improves a downstream model, nor that it is free of bias or hallucination. It measures pipeline yield and economics under a stated configuration.

---

## 2. Methodology (fill for every run)

### 2.1 Hardware
- CPU model / cores / threads
- RAM (GB)
- GPU (model / VRAM / count) or `none`
- Disk type / free space
- OS + kernel version
- Python version

### 2.2 Software versions (pin everything)
- Knovaryn commit or version
- Docling version (and extra)
- DocETL version (if the `docetl_gather` profile is used)
- LiteLLM version (if used)
- Parser engine + OCR config used
- Chunker engine + config hash (structure_aware config: `target_tokens`, `min_tokens`, `max_tokens`, `neighbor_context_tokens`, `keep_tables_together`, `keep_lists_together`)
- Model gateway profiles: generator / critic / verifier / embedding model IDs + versions (or `FakeProvider`)

### 2.3 Corpus
- Name and redistribution rights of the corpus (must be permitted; record declared license status per source)
- Number of documents, formats (PDF with tables? text-only?), page/sheet counts
- Total byte size; SHA-256 of each source as ingested
- Whether OCR was required; OCR engine + mode

### 2.4 Warm-up and concurrency
- Warm-up: describe pre-run warm-up (e.g., N iterations to populate caches) — required so the first-run penalty isn't misreported
- Concurrency settings (worker count / parallel chunkers / batch size)
- Repetitions: report at least 3 runs for the headline numbers; state min/median/max

### 2.5 Sample size and plan
- Target examples (`target_examples`), topologies (sft / preference / evaluation), task-family and difficulty distributions
- Split policy (train/validation/test), seed
- Number of accepted examples actually produced vs. target
- Human-review sample fraction used (default `human_review_sample: 0.05`)

### 2.6 Errors and outliers
- Job states at end (succeeded / failed / partial / cancelled)
- Worker failures, retries (`max_attempts`), checkpoint resumes observed
- Any error codes/summaries
- Exclude or flag outliers explicitly

---

## 3. Metrics definition

- **Accepted-example yield:** `accepted / attempted` (and `accepted / target`). Report reason-code breakdown for rejections (e.g., `grounding<0.9`, `overall<0.82`, `preference_signal<0.7`, high-confidence PII, blocked license, injection pattern).
- **Duplicate rate:** fraction of exported examples rejected/removed as near-duplicate by content hash or dedup (report the dedup method). This is expensive-work-avoidance signal.
- **Cost per accepted example:** `total_cost_usd / accepted_count`. `total_cost_usd` from the cost ledger (`actual_cost`), *excluding* (and separately reporting) the human-review cost. Report token counts (prompt/completion) and model prices used (dated price profile) so readers can recompute.

---

## 4. Report template

```markdown
# Knovaryn Benchmark Report

- Report ID / date:
- Benchmark author(s):
- Methodology version (link to this file):
- Full reproducibility: config files, corpus manifest, and run logs at:

## Environment
- Hardware: <...>   Software: <...>

## Corpus
- <per §2.3>

## Config
- Profile: <offline-demo|fast-local|balanced|high-quality|...>
- Chunker: <structure_aware|docetl_gather|fixed_character>
- Plan: <topologies, target, split, seed, human-review fraction>

## Runs
- Warm-up: <...>   Concurrency: <...>   Repetitions: <...>

| Metric | Run 1 | Run 2 | Run 3 | Median |
|---|---|---|---|---|
| Attempted examples | | | | |
| Accepted examples | | | | |
| Accepted-example yield | | | | |
| Rejected by reason (top) | | | | |
| Duplicate rate | | | | |
| Total cost (USD) | | | | |
| Cost per accepted (USD) | | | | |
| Tokens (prompt/completion) | | | | |
| Wall time | | | | |

## Errors / outliers
- <job states, retries, checkpoints, failures per §2.6>

## Interpretation (honest)
- What this does and does not show. No model-improvement claim. No bias/hallucination claim.
```

---

## 5. Standard comparison targets

Report all three chunking paths on the **same** corpus, environment, plan, and a **fixed-provider** setup where possible (the deterministic FakeProvider for a zero-cost baseline; then a live provider under a capped budget):

1. **Fixed-character chunks** — naive fixed-size splitting (baseline that ignores structure).
2. **Structure-aware (`structure_aware`)** — Knovaryn default: heading hierarchy, table/list preservation, sentence/token budgets, neighbor context.
3. **DocETL gather (`docetl_gather`)** — optional advanced profile (requires `docetl` extra).

For each path report: accepted-example yield, duplicate rate, cost per accepted example, wall time, and reject-reason distribution.

**Comparison integrity rules:**
- Same corpus, same plan, same seed.
- Warm-up applied to every path equally.
- Report 3 repetitions; never cherry-pick the best.
- State clearly if a path produced structurally different chunk counts (that *is* the point) — do not normalize silently.

---

## 6. Checklist before publishing a report

- [ ] Every methodology field filled; nothing assumed.
- [ ] Versions pinned (commit hashes where possible).
- [ ] Corpus redistribution rights recorded and confirmed permitted.
- [ ] ≥3 repetitions, median reported, best-run not cherry-picked.
- [ ] Cost model dates + prices included so readers can recompute.
- [ ] Errors/outliers reported, not hidden.
- [ ] Explicit "no model-improvement / no bias-freedom claim" note present.
