# Knovaryn — Media / Press Factsheet

**Document status:** DRAFT — finalize before outreach.
**Prepared:** 2026-08-07 · **Contacts:** see `SECURITY.md` and repo maintainers (add journalist contact line before outreach).

---

## 2-second summary

**Knovaryn** is a free, open-source (Apache-2.0), MCP-native training-data foundry that turns permitted documents into **traceable, quality-gated SFT and preference datasets** that any MCP-capable agent can build, review, and export.

**Tagline:** *From documents to defensible training data.*
**One-liner:** "Turn permitted documents into traceable, quality-gated SFT and preference datasets that any MCP-capable agent can build, review, and export."

---

## Key facts

| Item | Value |
|---|---|
| Product / category | Open-source training-data engineering (MCP-native) |
| Release | Version 0.1.0 (alpha); public 1.0 gate documented |
| License | Apache-2.0 |
| Language / runtime | Python ≥ 3.11 |
| Interfaces | MCP server (`knovaryn_mcp`), CLI, partial REST/web |
| Parsing | Docling (canonical DoclingDocument JSON; markdown/text derived) |
| Chunking | Structure-aware default; optional DocETL gather profile |
| Model gateway | OpenAI-compatible, Anthropic-compatible, DeepSeek; deterministic fake provider (offline) |
| Exports | TRL conversational, LLaMA-Factory ShareGPT, canonical JSONL, Parquet |
| Profiles | offline-demo, fast-local, balanced, high-quality, air-gapped, enterprise |
| Repository | <github URL — set before publish> |

---

## Positioning

- **Category:** Open-source, MCP-native training-data engineering.
- **Problem:** Small applied-LLM teams can't connect *permitted documents* to *defensible datasets* — examples lack evidence, weak rows get shipped, killed jobs double-spend, and output is locked to one trainer.
- **Differentiation (5 pillars):**
  1. Trace every example — evidence spans + lineage, enforced.
  2. Resume expensive work — checkpointed, idempotent jobs (no duplicate spend).
  3. Bring your own model and trainer — provider + export adapters.
  4. Run local or governed — offline demo + remote auth.
  5. Measure quality, not merely generate — acceptance reasons + benchmark reports.

## Who it's for
Applied-LLM teams; domain practitioners (finance/law/compliance/support); MCP developers; consultants producing custom datasets; researchers publishing redistributable public datasets.

---

## The numbers to quote (only if true at time of writing)

- Version and release date
- What the offline demo requires: **no API keys, no network**
- Target market: long-tail custom models, not frontier-scale pretraining

## Honest-limitation boilerplate (include in every pitch)

> Knovaryn measures quality against a configurable policy; it does **not** guarantee the absence of bias or hallucination, and does **not** guarantee that generated data improves any model. Its license handling gates blocked/unknown sources for public export but is **not** legal clearance. It is an alpha (0.1.0) and APIs are not yet stabilized.

---

## Suggested talking points for interviews

1. Why MCP-first: the agent drives the pipeline; Knovaryn owns durable state.
2. Evidence as a first-class data property, not a promise.
3. Resume-after-disconnect as a real cost property, not a feature bullet.
4. Honest QA: score, reason-code quarantine, and why that's likelier than "just generate."
5. The value of an offline, key-free demo for responsible experimentation.

## Do NOT claim (hard limits)
- No legal clearance / no bias-free / no hallucination-free / no "guaranteed model improvement."
- No comparison benchmark numbers unless reproduced via `benchmark-methodology.md`.
- Do not present Knovaryn as a Docling or DocETL replacement; it composes with them.

---

## Assets / boilerplate
- Logo: see `logo-brief.md` (a brief, not a finalized trademarked logo).
- Release notes: `release-notes-0-1-0.md`.
- Peer comparison: `peer-comparison.md`.
- Benchmark methodology: `benchmark-methodology.md`.
- Release gate (1.0): `release-gate.md`.
