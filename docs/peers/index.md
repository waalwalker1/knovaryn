# Peer Landscape

How Knovaryn sits among related open-source tools for document-to-training-data
work. This page is **not a benchmark** — capabilities are "documented present /
absent" as of review, and projects move fast. Verify against live repos before
relying on a claim. Where we are unsure, we say so rather than guess.

## Landscape at a glance

| Tool | Primary focus | MCP | Doc→dataset | Evidence/trace | Resumable jobs | Quality gate | Trainers/export |
|---|---|---|---|---|---|---|---|
| **Knovaryn** | MCP-native training-data foundry | Native | Yes | Strong (spans, hash, lineage) | Yes (checkpointed) | Yes (scores + quarantine) | TRL, LLaMA-Factory, JSONL, Parquet, HF |
| Meta Synthetic Data Kit | LLM-data agent framework / SDK | No (native) | Partial | Partial | Partial | Partial | Custom/JSON |
| Easy Dataset | Dataset generation/enrichment | Partial | Partial | No | No | Partial | JSON/others |
| Augmentoolkit | LLM data augmentation/eval | Some | Partial | Partial | No | Partial | Many formats |
| Distilabel (Argilla) | Data pipeline + LLM-as-judge | Some/integration | Partial | Partial | No | Yes (scores) | Many (incl. Argilla) |
| Bespoke Curator | Dataset generation & curation | No | Partial | Partial | No | Yes (curation) | Parquet/JSON |
| Docling MCP | Document parsing/OCR MCP tools | Yes | No (parse-only) | No | No | No | N/A (parsing) |
| DocETL | Declarative ETL for AI | No (planned) | Yes | Partial | Partial | No | JSON/others |

"Partial" means the project has something in that area but it is not a central,
fully documented facility as of review (or we could not confirm it from docs).

## How Knovaryn differs (honestly)

1. **MCP is the interface, not a wrapper.** You drive the whole foundry from an
   MCP agent (`knovaryn_mcp`); the CLI mirrors the same verbs. State lives in
   Knovaryn's durable engine.
2. **Evidence-linked records.** `source_document_ids`, `source_span_ids`,
   `content_hash`, and generation-candidate IDs are first-class and enforced by
   a provenance minimum — exports can carry them so a dataset card points at
   where each row came from. Most peers keep some metadata but not
   span-level, enforced evidence.
3. **Durable, resumable jobs.** Leased workers, heartbeats, checkpoints,
   idempotency keys. A killed run resumes without duplicate token spend — a
   concrete cost property most peers do not centralize.
4. **Quality gate with reasons.** Candidates are scored across dimensions
   against a dated policy; weak rows are quarantined with a reason code and
   never export.
5. **Canonical schema and exporters.** One canonical `DatasetVersion` exports to
   TRL, LLaMA-Factory, OpenAI chat, ShareGPT, Alpaca, Parquet, and Hugging Face —
   bring your own trainer.
6. **Local-to-enterprise.** Offline-demo profile with a deterministic fake
   provider runs with no keys; scope-based auth + admin policy and
   PostgreSQL+S3 for governed teams.

## Where the peers lead (be honest)

- **Docling / Docling MCP** are the stronger general parsing/OCR story; Knovaryn
  depends on Docling for parsing.
- **DocETL** is more flexible than Knovaryn's optional gather profile for exotic
  extraction over big collections.
- **Distilabel** has a more mature, battle-tested LLM-as-judge ecosystem and an
  Argilla review workflow.
- **Synthetic Data Kit / Distilabel** have larger communities and more adapters
  today.
- **Augmentoolkit / Easy Dataset / Bespoke Curator** are strong if you want
  heavy augmentation and many output formats without span-level traceability.

## When to use another tool

- Need high-fidelity parsing/OCR of messy scans → **Docling / Docling MCP**.
- Need powerful declarative extraction across large collections → **DocETL**.
- Want a mature pipeline plus Argilla annotation/judge UI, and don't need
  MCP-first → **Distilabel**.
- Want heavy data augmentation and many output formats and don't need
  traceability → **Augmentoolkit / Easy Dataset / Bespoke Curator**.
- Want an LLM-agent data framework with a Python SDK → **Meta Synthetic Data
  Kit**.
- Want an MCP-native, evidenced, gated, resumable document→dataset loop with
  your own model and trainer → **Knovaryn**.

## Caveats

- A checkmark means "documented present," not "better at it."
- No comparison benchmark numbers here; reproduce everything with
  `benchmark-methodology.md` before quoting numbers anywhere.
- Knovaryn composes with Docling and DocETL rather than replacing them, and
  is not a substitute for a general data ETL or annotation suite by itself.
