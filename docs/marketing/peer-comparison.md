# Knovaryn — Peer Comparison

**Document status:** DRAFT — refresh before each public release.
**Last updated:** 2026-08-07.
**Intent:** A factual comparison page for buyers and contributors choosing a document→training-data tool. Where we are unsure about a peer's current capabilities, we say so rather than guessing. **This is not a benchmark** — no performance numbers here. For reproducible numbers, see `benchmark-methodology.md`.

---

## 0. Transparent methodology (read this first)

This table was assembled **by reading each project's public README/docs/repo as of 2026-08-07**, not by installing or stress-testing every tool. Caveats:

- **Recency.** All of these projects move fast. Capabilities marked "yes / partial / no" can change within weeks. **Verify against the live repo before publishing.** We have not re-verified each peer on the publication date.
- **What a "✔" means.** A feature exists in the project's public docs — it does not mean Knovaryn or the peer is *better* at it, only that the capability is present/absent.
- **We did not run benchmarks.** A checkmark is not a quality score. Treat gaps as "not the documented focus," not "bad."
- **Scope.** All eight peers are legitimate and useful for different jobs. "Knovaryn differences" is about packaging, traceability, and MCP-first ergonomics — not an assertion that Knovaryn is superior overall.

If you maintain one of these projects and believe a row is wrong or dated, open an issue or PR on the comparison and we'll correct it.

---

## 1. Landscape at a glance

| Tool | Primary focus | MCP | Doc→dataset | Traceability/evidence | Resumable jobs | Quality gate | Trainers/export |
|---|---|---|---|---|---|---|---|
| **Knovaryn (this project)** | MCP-native training-data foundry | Yes (native) | Yes | Strong (spans, hash, lineage) | Yes (checkpointed) | Yes (scores + quarantine reasons) | TRL, LLaMA-Factory, JSONL, Parquet |
| Meta Synthetic Data Kit | Open-source agent/data framework | No (native) | Partial | Partial | Partial | Partial | Custom/JSON |
| Easy Dataset | Dataset generation/enrichment | Partial/adhoc | Partial | No | No | Partial | JSON/others |
| Augmentoolkit | LLM data augmentation/eval | Some | Partial | Partial | No | Partial | Many formats |
| AI-Dataset-Generator | Dataset generation loop | No | Partial | No | No | Partial | CSV/JSON/Parquet |
| Distilabel (Argilla) | Data pipeline framework, LLM-as-judge | Some/integration | Partial | Partial | No | Yes (scores) | Many (incl. Argilla) |
| Bespoke Curator | Dataset generation & curation | No | Partial | Partial | No | Yes (curation) | Parquet/JSON |
| Docling MCP | Document parsing/OCR MCP tools | Yes | No (parse-only) | No | No | No | N/A (source parsing) |
| DocETL | Declarative ETL for AI (map/split/gather) | No (native, planned) | Yes | Partial | Partial | No | JSON/others |

*"Partial" = the project has something in this area but it isn't a central, fully-documented facility as of the review date, or we could not confirm it from docs. Confirm against live repos.*

---

## 2. Capability detail

### Parsing / chunking
- **Knovaryn:** Docling-first parsing with structure-aware chunking (headings, tables, lists, neighbor context) as default; optional DocETL gather profile.
- **Docling MCP:** focused on high-fidelity document → markdown/structured parsing over MCP; does **not** generate training examples or manage datasets.
- **DocETL:** powerful map/split/gather declarative ETL over docs/DBs; strong at complex extraction; not a dataset-quality validator.
- **The generation-focused peers (Easy Dataset, AI-Dataset-Generator, Augmentoolkit, Bespoke Curator, Synthetic Data Kit, Distilabel):** generally treat chunking/parsing as a step to feed generation rather than a structically-aware, evidence-preserving core.

### MCP-native-ness
- **Knovaryn:** MCP is the primary interface (server id `knovaryn_mcp`).
- **Docling MCP:** MCP-native but parse-focused.
- **Others:** MCP where present is a bolt-on or absent; Distilabel is pipeline/CLI and integrates into Argilla; Synthetic Data Kit is an SDK/agent runtime.

### Traceability (evidence spans, hash, lineage)
- **Knovaryn:** first-class `source_document_ids`, `source_span_ids`, `content_hash`, generation-candidate IDs; line from example → page/section.
- **Distilabel / Bespoke Curator:** keep source and generation metadata but not span-level evidence-pointing as a first-class, enforced property.
- **Augmentoolkit / Synthetic Data Kit:** track some provenance but span-level evidence is not the core guarantee.

### Resumable / idempotent jobs
- **Knovaryn:** checkpointed, idempotent, heartbeats, resume-without-duplicate-spend.
- **Most peers:** run generation as scripts/jobs without durable checkpointing; a killed run typically needs a restart.

### Quality gating
- **Knovaryn:** multi-dimension scoring + acceptance reasons + quarantine, policy versioned.
- **Distilabel:** offers LLM-as-judge scoring and can route to review/Argilla. Strong.
- **Bespoke Curator:** curation/filtering focus.
- **Synthetic Data Kit:** quality tools exist but are not the signature feature.
- **Easy Dataset / AI-Dataset-Generator / Augmentoolkit / DocETL:** validation is lighter or delegated.

---

## 3. Knovaryn differences (how we position, honestly)

1. **MCP is the interface, not a wrapper.** You drive the whole foundry from an MCP agent; the CLI mirrors the same verbs.
2. **Evidence is enforced, not decorative.** Exports can carry span-level provenance and hashes so dataset cards can say *where* each example came from.
3. **Durable resume is a money story.** Checkpointed, idempotent jobs avoid duplicate token spend on long billable runs — a concrete cost property most peers don't centralize.
4. **Quality gate with reasons.** Acceptance produces reason codes; weak rows are quarantined with their cause, and quarantined rows never export.
5. **License gate before public export.** Blocks/defers blocked and unknown licenses on the public path (a safety rail, not legal clearance).
6. **Local-first + governed.** Offline-demo profile with a deterministic fake provider runs the whole thing with no keys; scope-based auth and admin policy for teams.

**Where the peers lead (be honest):**
- **DocETL** is more flexible than our optional gather profile for exotic extraction.
- **Distilabel** has a richer, more battle-tested LLM-as-judge ecosystem and Argilla review workflow.
- **Synthetic Data Kit / Distilabel** have larger communities and more adapters today.
- **Docling / Docling MCP** are the stronger general parsing story; Knovaryn depends on Docling for parsing.

---

## 4. When to pick which

- Need high-fidelity parsing/OCR of messy docs → **Docling / Docling MCP**.
- Need powerful declarative extraction over big collections → **DocETL**.
- Want a mature pipeline + Argilla annotation/judge UI, don't need MCP-first → **Distilabel**.
- Want heavy data augmentation and many output formats, don't need traceability → **Augmentoolkit / Easy Dataset**.
- Want an LLM-data agent framework with Python SDK → **Meta Synthetic Data Kit**.
- Want an MCP-native, evidenced, gated, resumable document→dataset loop with BYO model/trainer → **Knovaryn**.

---

## 5. Verify before publishing

- [ ] Re-check each peer's README/repo on the intended publish date for capability drift.
- [ ] Confirm Knovaryn's own stated capabilities match what the pinned release actually ships.
- [ ] Add/keep the "last reviewed" date and the "no legal/bias claims" disclaimer.
- [ ] Link the release-gate and benchmark-methodology docs.
