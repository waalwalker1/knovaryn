---
description: >-
  Exporter reference: all dataset export formats (TRL
  SFT/preference, KTO, ShareGPT, Alpaca, OpenAI chat, HF layout,
  evaluation, JSONL, Parquet) and release bundles with checksums.
---

# Reference — Exporters and Release Bundle

Exporters adapt one **canonical `DatasetVersion`** to trainer-native formats.
The canonical version is the single source of truth; every format is a
projection of it, so you never maintain parallel pipelines per trainer.

## The `DatasetExporter` port

Each exporter implements:

```python
class DatasetExporter(Protocol):
    name: str

    async def export(self, version, *, writer, options): ...
```

The `name` is the value used with `--format <name>` and `exports.formats`.
Exporters consume the frozen version and write to the artifact store / release
directory.

## Format adapters

<!-- BEGIN GENERATED EXPORT FORMATS -->

Format ids are generated from `pipeline.export.formats.SUPPORTED_FORMATS`
— this table cannot drift from what `--format` accepts:

| Format | Media type |
|---|---|
| `alpaca` | `application/jsonl` |
| `evaluation` | `application/jsonl` |
| `huggingface_layout` | `application/jsonl` |
| `kto` | `application/jsonl` |
| `openai_chat` | `application/jsonl` |
| `sharegpt` | `application/jsonl` |
| `trl_preference` | `application/jsonl` |
| `trl_sft` | `application/jsonl` |
| `jsonl` | `application/jsonl` |

`jsonl` is the canonical passthrough (accepted by `--format` alongside
the ids above). Parquet is **not** a `--format` id: it is produced by
the SDK function `knovaryn.pipeline.export.export_parquet` (requires the
`parquet` extra) and by the release bundle's split files when that extra
is installed.

<!-- END GENERATED EXPORT FORMATS -->

Every format is a projection of the same frozen `DatasetVersion`; rows keep
explicit lineage fields (`source_document_ids`, `source_span_ids`,
`content_hash`) so provenance stays machine-checkable in every layout.
Parquet output requires the `parquet` extra; Hugging Face Hub upload
(`knovaryn dataset publish`) requires the `hub` extra and a passing
publication gate.

## What each row carries (config-dependent)

By default `exports.include_private_audit_metadata` is `false`, so trainer
formats carry:

- the messages (system/prompt/chosen/rejected per topology);
- `trainer_visible_metadata` (e.g. task family, difficulty, split);
- optionally, evidence references (`source_document_ids`, `source_span_ids`,
  `content_hash`) so a dataset card can point at where each row came from.

Private audit metadata (grounding internals, hidden reasoning notes, prompts
you chose not to store) stays out of public exports unless explicitly enabled.

## Release bundle layout

A version exports into a self-describing release tree, e.g. under the artifact
root / staging dir:

```
release/
├── manifest.json              # version, semantic, parent, counts, content hash
├── dataset-card.md            # train/val/test counts, target audience, mix
├── quality-report.json        # policy version, score distributions, reasons
├── source-manifest.json       # every source doc: sha256, license status, redacted locator
├── license-report.json        # per-source license classification
├── privacy-report.json        # PII findings (redacted), actions
├── data/
│   ├── canonical.jsonl
│   ├── openai_chat.jsonl
│   ├── sharegpt.jsonl  alpaca.jsonl  … (per selected format)
│   └── splits.parquet (train/validation/test when parquet extra installed)
└── lineage/                   # per-example evidence pointers (example -> span ids)
```

The artifact IDs for `manifest`, `quality_report`, `dataset_card`,
`source_manifest`, `license_report`, and `privacy_report` are recorded on the
`DatasetVersion` row so a version is self-documenting and reproducible.

## Publishing

`knovaryn dataset publish` is the **optional, gated** path: it performs a
`dry_run` (checks `licensing.public_export_requires_approved_sources`, privacy
report, and any `Publisher` constraints), produces a summary, and requires a
confirmation token before `publish`. This is a safety rail — it does not
constitute legal clearance or guarantee the absence of PII.

## Extending

Add a new trainer by implementing `DatasetExporter` and registering its `name`.
Because it consumes the canonical version, a new exporter immediately applies to
every existing and future dataset version.
