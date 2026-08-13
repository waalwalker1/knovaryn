# Guide — Hugging Face export

This guide covers getting Knovaryn datasets onto **Hugging Face**: exporting a
version in a Hub-friendly layout, and using the (default dry-run) **dataset
publish** flow to stage a Hub dataset with its dataset card and provenance.

> **Safety by default:** publication is **dry-run** unless you explicitly
> authorize it. Nothing is pushed anywhere by accident — see
> [dataset publication](../concepts/quality-gates.md) and the security model.

## Prerequisites

- Knovaryn installed — see the [quickstart](quickstart.md). For Hub publishing
  install the optional `hub` extra: `pip install "knovaryn[hub]"`.
- Permitted sources — [license and privacy](../concepts/license-and-privacy.md).

## Option A — Export a Hub-friendly JSONL locally

The `huggingface_layout` format exports a layout close to what Hub datasets and
chat/training frameworks expect, while retaining Knovaryn provenance:

```text
messages, topology, quality_score, source_document_ids, source_span_ids, content_hash
```

1. Build a version — `knovaryn_create_dataset_version`.
2. Export — `knovaryn_export_dataset` with `format=huggingface_layout`
   (or `parquet` via the `parquet` extra if you want arrow tables):

```bash
uv run knovaryn verify-release <bundle>.zip   # verify checksum + manifest
```

The release bundle ships a dataset card, manifests, and a detached checksum, so
you can publish it to the Hub knowing exactly what it contains.

## Option B — Publish to the Hub (dry-run, then authorize)

The publish flow targets a Hub `repo_id` and is **dry-run by default**:

1. `knovaryn_publish_dataset` with `repo_id: "your-org/your-dataset"` and
   `dry_run: true` — returns a full **publication plan**: destination, version,
   immutability/provenance/quality/license/privacy gate status, detached
   checksum, and the planned artifact list. **No external side effect.**
2. Review the plan. If a gate is not satisfied, publication is **refused**
   (fail closed).
3. Only with explicit authorization does a real push happen (the tool requires
   `authorized`/confirmed state, and the `huggingface-hub` extra installed).

> Publishing to Hugging Face is an outward-facing action. Knovaryn never pushes
> automatically — the owner must explicitly enable the external side effect.

## What gets published

A Hub dataset built by Knovaryn includes the training records plus a dataset
card that records `name`/`language`, the version, the detached checksum, and
the provenance chain, so consumers can verify what they are using.

## Related

- Reference — [exporters](../reference/exporters.md).
- Concepts — [dataset provenance](../concepts/dataset-provenance.md), [quality gates](../concepts/quality-gates.md).
- Guides — [PDF → SFT dataset](pdf-to-sft-dataset.md), [build DPO preference data](build-dpo-preference-data.md).
