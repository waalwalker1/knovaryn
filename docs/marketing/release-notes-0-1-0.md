# Knovaryn 0.1.0 — Release Notes

**Date:** 2026-08-07 (draft — finalize before public tag)
**License:** Apache-2.0
**Python:** ≥ 3.11
**Distribution:** `knovaryn` on PyPI (verify name availability per `release-gate.md` — this is a draft)
**Classifier status:** `Development Status :: 3 - Alpha`

This is the first public release. It is a **0.x alpha**: APIs are not yet stabilized and the 1.0 gate ("release-gate.md") has not been passed. We are publishing early to get feedback on the pipeline and the quality heuristics.

---

## Highlights

- **MCP-native pipeline.** `knovaryn mcp --profile offline-demo` exposes the full foundry as Model Context Protocol tools (create project, add source, plan + dry-run estimate, run, review, export) so any MCP-capable agent can drive it. The CLI exposes the same pipeline (`knovaryn project|source|plan|run|review|export|dataset ...`).
- **Document intake with license gate.** `knovaryn source add` preflights a document (SHA-256, size, page/sheet count, declared + detected license). License classification (`allowed` / `review` / `blocked`) gates whether content may enter a public export; blocked or unknown sources are refused for public paths by default.
- **Docling parsing with output checkpoints.** The default parser persists the canonical DoclingDocument JSON; markdown, text, and table artifacts are derived. A resource guard manages Docling memory/worker recycling (`worker_recycle_documents`). When the `docling` extra is absent, intake degrades to a documented safe text/markdown adapter so the offline demo still runs.
- **Structure-aware chunking (default).** Uses the Docling tree, heading hierarchy, sentence/token budgets, table boundaries, and neighbor context. Tables and lists stay together. Deterministic; no undocumented model calls.
- **Optional DocETL gather profile.** Behind the same `Chunker` interface, gated by the `docetl` extra; otherwise raises an explicit `ConfigurationError`. Never makes an undocumented model call; outputs canonical `Chunk` records; supports dry-run estimates.
- **Durable, resumable job engine.** Leased workers, heartbeats, output checkpoints, idempotency keys. A killed worker resumes from its checkpoint without regenerating finished chunks (no duplicate token spend).
- **Provider-agnostic model gateway.** OpenAI-compatible, Anthropic-compatible, and DeepSeek (via OpenAI-compatible base URL) adapters are opt-in. A deterministic **fake provider** is the default for CI, examples, and the offline demo — no credentials required. Cost is priced from a dated, overridable price profile.
- **Validation with reasons.** Candidates are scored across dimensions (grounding, instruction fulfillment, preference signal, artifact resistance) against a dated acceptance policy. Acceptance records reason codes; weak examples are quarantined with a reason (e.g., `grounding<0.9`). High-confidence PII and blocked licenses reject by default.
- **Preference-pair hygiene.** Pairs pass a length-ratio band and a superficial-artifact separator (refusal phrases, formatting markers), with a `rejected_defect` taxonomy and expected preference margin.
- **Canonical data + provenance.** Every example carries `source_document_ids`, `source_span_ids`, `content_hash`, and generation-candidate IDs — full lineage to the original page/section.
- **Versioned export.** One canonical dataset version exports to TRL conversational, LLaMA-Factory ShareGPT, canonical JSONL, and Parquet.
- **Profiles.** `offline-demo`, `fast-local`, `balanced`, `high-quality`, `air-gapped`, `enterprise`. OAuth-style resource scopes and admin-enforced security policy for governed environments.

---

## Installation

```bash
pip install -e ".[dev]"        # lean core + dev
# optional: pip install -e ".[docling,docetl,litellm,parquet,hub,ml,s3]"
```

```bash
knovaryn init                   # create .knovaryn/ state dir
knovaryn mcp --profile offline-demo
```

## What's not in 0.1.0 (on purpose)

- Not yet a 1.0; no stability guarantee on APIs or formats.
- No claim of bias-free or hallucination-free output, and no claim that generated data improves any model.
- License handling is a gate, not legal clearance.
- Standard benchmarks against external corpora are not yet published (see `benchmark-methodology.md` for the template and `benchmarks/` for the harness).
- Web console and REST surface are partial; the CLI and MCP server are the supported interfaces.

## Known limitations / issues

- Live-provider tests are opt-in behind explicit env flags and a spending cap.
- The MCP tool surface and CLI flags are the same pipeline today but not yet synchronized in every edge case.
- Performance and memory have been exercised in tests, not yet benchmarked at production scale.

## Future direction (see roadmap)

Stabilized 1.0 APIs, public benchmark reports, more exporters and validators, richer DocETL profile, and a sample redistributable dataset (proposal in `sample-dataset.md`).

---

*Feedback, issues, and pull requests welcome. See `SECURITY.md` for coordinated disclosure.*
