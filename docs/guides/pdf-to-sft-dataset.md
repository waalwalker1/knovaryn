---
description: >-
  Turn permitted PDFs into an SFT dataset: parse, chunk, generate,
  gate, review, version, and export — every step traced to page-
  level evidence.
---

# Guide — PDF to SFT dataset

This guide walks a **PDF → SFT dataset** pipeline in Knovaryn: ingest permitted
PDFs, parse them with Docling, split into structure-aware chunks, generate
supervised fine-tuning (SFT) examples, gate them for quality, and export a
trainer-ready **JSONL** (or Parquet) dataset.

> **What you get:** a supervised fine-tuning dataset where every accepted
> example carries evidence references that walk back to its source spans at a
> machine-reported location precision (Docling-parsed PDFs yield
> `exact_page`/`exact_bbox`), and where weak or ungrounded examples are
> quarantined instead of exported.

## Prerequisites

- Knovaryn installed — see the [quickstart](quickstart.md).
- PDFs you are **permitted** to use — see [license and privacy](../concepts/license-and-privacy.md).
- No API keys required for the offline demo; a real model provider is optional
  (see [first real project](first-real-project.md)).

## Interfaces

Knovaryn exposes the pipeline through four interfaces that share one
application-services core: a [Model Context Protocol server](../concepts/overview.md),
a CLI (`knovaryn demo`, `knovaryn doctor`, `knovaryn verify-release`), a REST
API + web console, and the Python SDK. This guide drives it with the **MCP
tools** (the primary, MCP-native interface) — see
[MCP client setup](mcp-clients.md) to connect your agent.

## 1. Create a project

Call **`knovaryn_create_project`**:

- `name: "Technical-Manual SFT"`
- `slug: tech-manual-sft`
- optionally `description`

## 2. Add your PDFs with declared licenses

Call **`knovaryn_add_source`** for each permitted PDF:

- `file_path: ./docs/manual-1.pdf`
- a **source license** (the pipeline resolves rights from the source-license
  registry; the [license gate](../concepts/quality-gates.md) blocks samples
  whose sources are not permitted)

Optionally call **`knovaryn_inspect_source`** to confirm the parse diagnostics
and quality summary, and **`knovaryn_license_report`** to review the rights it
recorded.

## 3. Plan, then start the pipeline (SFT topology)

Call **`knovaryn_estimate_run`** first for a **dry-run cost estimate** (so
nothing is spent before you review the plan). Then call
**`knovaryn_start_pipeline`** with an SFT/generation topology. The pipeline
parses the PDFs into canonical Docling JSON, splits at the source group, chunks
structure-aware (headings, tables, lists), and generates SFT
`(instruction, response)` pairs grounded in the chunk text.

Track progress with **`knovaryn_get_job`** / **`knovaryn_list_jobs`**. Every
stage runs as a durable job (leases, heartbeats, checkpoints) — a crash resumes
from the last checkpoint instead of redoing paid work.

## 4. Review the examples

Call **`knovaryn_preview_examples`**. Each candidate carries
`source_document_ids`, `source_span_ids`, and a `content_hash`, so you can hop
back through `knovaryn_lineage` to the supporting spans — with each span's
machine-reported location precision (page/section granularity for
Docling-parsed PDFs) returned alongside.
Use **`knovaryn_review_example`** to record an approve/reject decision — a
review creates a new immutable revision, it never mutates the example in place
(see [review & revisions](../concepts/quality-gates.md)).

## 5. Validate and gate

Call **`knovaryn_validate_dataset`**. The
[quality gate](../concepts/quality-gates.md) runs schema, grounding, format,
refusal, dedupe, contamination, privacy, and license validators. Failures are
**quarantined**, never exported.

## 6. Version and export SFT JSONL (or Parquet)

Call **`knovaryn_create_dataset_version`** to snapshot the accepted examples
(an immutable version — later reviews cannot silently change it), then call
**`knovaryn_export_dataset`** with `format=openai_chat` to get a trainer-ready
JSONL bundle with a detached checksum and per-file manifest.

> Knovaryn also exports `trl_sft`, `alpaca`, `sharegpt`, and Parquet — see the
> [exporter reference](../reference/exporters.md). `knovaryn verify-release`
> independently verifies any release bundle's detached checksum + manifest.

## Verify everything offline

The bundled offline demo runs the complete loop on sample documents with a
deterministic fake provider and **no API keys or network**:

```bash
uv run knovaryn demo --examples 20 --json
uv run knovaryn doctor        # environment + storage health
```

## What you can do next

- Build **preference/DPO** pairs — [build DPO preference data](build-dpo-preference-data.md).
- Push to the Hub — [Hugging Face export](hugging-face-export.md).
- Understand the guarantees — [dataset provenance](../concepts/dataset-provenance.md).
