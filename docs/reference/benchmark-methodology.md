---
description: >-
  How Knovaryn benchmarks are run and scored: fixed corpora,
  seeded providers, environment capture, three-run medians, and
  bundle digests for reproducibility.
---

# Benchmark methodology

This page is the **canonical methodology** for every Knovaryn benchmark report.
Reports under `benchmarks/` cite this page by version; if the methodology
changes, new reports are cut and old reports keep their historical values
unchanged (see `benchmarks/report-0-1-0.md` in the repository for the
v0.1.0-era historical example).

**The one rule this page exists to enforce:** every published number is either
reproducible from a committed command, or explicitly labeled *not measured*.
Fake-provider results are never substituted for live-provider claims.

## 1. Benchmark categories

| # | Category | What it measures |
|---|----------|------------------|
| 1 | Parse fidelity | Parse success rate; structure extraction (heading coverage) per source format |
| 2 | Chunk & span yield | Chunks and evidence spans produced per source |
| 3 | Provenance resolution | Share of accepted examples whose document/span references resolve to real pipeline entities |
| 4 | Precision distribution | Distribution of machine-verifiable span `precision` (`exact_bbox` … `unknown`) |
| 5 | Generation validity | Candidates → accepted / quarantined / review outcomes through the quality gates |
| 6 | Semantic quality | Adversarial false-accept / false-reject rates of the semantic layer, with Wilson intervals |
| 7 | Preference quality | Pairwise order-consistency, identical/near-duplicate rejection, defect requirement |
| 8 | Information gain | Rejection rate of the information-gate on no-signal candidates |
| 9 | Export compatibility | Round-trip status of every supported export format with resolvable lineage |
| 10 | Framework overhead | Wall-clock and examples/second of the offline pipeline — **not generation throughput** |
| 11 | Memory | Peak allocated bytes (`tracemalloc`) during an end-to-end run |
| 12 | Release reproducibility | Release-bundle size + SHA-256 equality across repetitions |
| 13 | Crash recovery | Job-engine kill/resume success and duplicate-work avoidance |
| 14 | Deployment | Compose E2E (PostgreSQL + MinIO) results when the environment provides them |

## 2. Corpus provenance and license rules

- The committed corpus lives in `benchmarks/corpus/` (manifest and per-file
  SHA-256 there); its bytes are the fixtures under `tests/fixtures/intake/`.
- Every corpus file is **authored by the project maintainers**, contains **no
  third-party material**, and is licensed Apache-2.0 with the repository.
- Reports must pin each source file's SHA-256 so a reader can prove their
  inputs match. A run over uncommitted or mutated corpus bytes is invalid.
- Permitted-use rules that apply to datasets apply to benchmarks: no corpus
  file may embed scraped or licensed third-party content.

## 3. Environment recording

Every report ships `environment.json` capturing: OS name/version/build,
machine architecture and CPU count, total RAM, Python implementation+version,
Knovaryn version (authoritative `__version__`), commit SHA the run was made
from, installed optional extras relevant to the run, provider backend, and
the UTC timestamp of the run. A report whose environment cannot be stated is
not publishable.

## 4. Warmup and repetition policy

- One untimed **warmup invocation** precedes timing runs (imports, parser
  tables, allocator warm-up). Warmup output is discarded.
- Unless stated otherwise, a report is the aggregate of **at least three
  repetitions** (`run-1.json` … `run-N.json`). Aggregates report the median;
  per-run values stay visible.
- Timing metrics are never averaged across different code versions.

## 5. Deterministic seed policy

- The default provider is the deterministic `FakeProvider`; sampling
  parameters are fixed in the runner (`temperature 0`, fixed seeds).
- `IdGenerator` instances are created fresh per run; all IDs derive from
  deterministic handles.
- Any metric that cannot be made deterministic (e.g., live providers) must be
  reported with repetition spread, not as a single number.

## 6. Fake-provider vs live-provider

- **Fake-provider (offline) runs** measure the *framework*: parsing, chunking,
  provenance assembly, validation gates, export, job engine. They are free,
  deterministic, network-free, and CI-runnable.
- **Live-provider runs** additionally involve model behavior and cost. They are
  only reported from environments that actually invoked a configured provider,
  with the provider/model recorded.
- **Substitution is forbidden**: a fake-provider number may never be presented
  as live-model throughput, quality, or cost. When no live provider was
  available, the report says `not measured`.

## 7. Framework overhead vs generation throughput

Framework overhead = wall-clock of the offline pipeline end-to-end ÷ produced
examples. It bounds the *non-model* cost of running Knovaryn. Generation
throughput in real deployments is dominated by the chosen provider and is
measured only by live-provider runs. Graphics and prose must carry the context
label: *"Offline deterministic framework benchmark — not live-model generation
throughput."*

## 8. Semantic-quality metrics

The adversarial semantic benchmark evaluates the deterministic claim-verifier
layer (the layer every install can execute) against labeled contradiction /
entailment cases:

- **False-accept rate (FA)** — expected `contradicted`, observed `entailed`.
  The worst failure for a quality gate; target 0.
- **False-reject rate (FR)** — expected `entailed`, observed `contradicted`.
  Bounded by the documented envelope (< 1/3 of entailment cases).
- Cases where the deterministic layer correctly reports `unverified` are
  neither FA nor FR; they are reported as coverage limits.
- The certified (`certified-semantic`) judge is measured separately, only when
  a reachable judge provider exists; unavailable judges yield `unverified`,
  never `verified`.

## 9. Preference-quality metrics

For preference (DPO-style) authoring:

- **Order-consistency rate** — share of pairs where a two-order certified
  pairwise judgment agrees across randomized presentation order.
- **Identical/near-duplicate rejection rate** — pairs whose chosen/rejected
  sides are identical or near-duplicates must be rejected (rate expected 1.0).
- **Real-defect requirement** — rejected sides must carry a classified defect;
  style-only differences do not qualify.
- Judge-based certification inherits provider limitations and is labeled as
  such wherever cited.

## 10. Provenance metrics

- **Lineage resolution rate** — accepted examples whose
  document/span/candidate references all resolve (target 1.0).
- **Precision distribution** — histogram of `SourceSpan.precision` values,
  demonstrating honest degradation (markdown/text sources cap at
  section/chunk rather than fabricating pages).

## 11. Release-reproducibility metrics

Under identical inputs and reproducible mode, the final release bundle digest
must satisfy:

H(R₁) = H(R₂) = H(R₃)

where H(Rᵢ) is the release-bundle SHA-256 of repetition *i*. A report also
publishes the bundle size and the digest itself. Digest inequality fails the
report: it means some input, ordering, or timestamp leaked nondeterminism into
the artifact.

## 12. Crash-recovery metrics

- **Crash-resume success rate** — jobs killed mid-stage and restarted complete
  successfully from checkpoints (target 1.0 over the exercised scenario set).
- **Duplicate provider-call count** — after resume, logical calls already
  recorded in the durable `model_calls` ledger must not be re-invoked
  (target 0 duplicates).
- **Duplicate cost-event count** — resumed jobs write no second cost event for
  an already-recorded call (target 0).

## 13. Deployment metrics

Compose E2E (API + worker + PostgreSQL + MinIO) results: pipeline completion
through the deployed stack, artifact round-trip through object storage, and
claim-exclusivity under concurrent workers. These require Docker and are
reported only from environments that ran them; otherwise `not measured here —
see deploy-e2e workflow`.

## 14. Confidence intervals

Proportions are reported with **Wilson 95% score intervals**

$$\text{CI} = \frac{p + z^2/2n \pm z\sqrt{p(1-p)/n + z^2/4n^2}}{1 + z^2/n},\quad z=1.96$$

computed over the actual case count n. Point estimates without intervals are
not acceptable for rates derived from finite case sets.

## 15. Outlier policy

- Timing outliers are **reported, never silently dropped**: aggregates use the
  median, and per-run values are always included in the results directory.
- A run that errors is either fully re-run or reported as failed; partial
  substitution is forbidden.
- If a metric varies between deterministic repetitions beyond its digest-
  equality guarantee, the report is invalid until the cause is fixed — variance
  in a deterministic system is a bug signal, not noise to be averaged away.

## 16. Limitations

Every report carries a limitations section stating at minimum: fake-provider
results say nothing about model quality; synthetic corpora exercise structure,
not linguistic diversity; framework overhead does not predict end-to-end
latency with a live provider; environment-specific timings are not portable
across hardware; and absence of a measurement (live cost, Docling layout, GPU)
must be visible, not implied.

## 17. Exact reproduction commands

```bash
# full current-release benchmark (writes benchmarks/results/<version>/)
uv run python benchmarks/run_report.py --version 0.2.1 --runs 3

# quick single-pass suite (stdout summary)
uv run python benchmarks/bench_suite.py

# verify the committed results reproduce byte-identically
uv run python benchmarks/run_report.py --check benchmarks/results/0.2.1
```

Reproduction requires no network access and no API keys.

## 18. Report schema

A report directory `benchmarks/results/<version>/` contains:

| File | Content |
|------|---------|
| `environment.json` | §3 environment record |
| `run-1.json` … `run-N.json` | one schema-fixed metric dict per repetition |
| `aggregate.json` | medians + Wilson intervals + digest-equality verdict |
| `checksums.txt` | SHA-256 of every other file in the directory |
| `README.md` | how these files were produced + verification command |

`benchmarks/report-<version>.md` is the human-readable narrative built from
those files and must link them. Metric keys are stable across versions; adding
a key is allowed, renaming or silently removing one requires a methodology
version bump noted in the changelog.

---
*Methodology version: 2 (2026-08-25). Version 1 was the inline methodology of
the v0.1.0 report; see that report for its historical statement.*
