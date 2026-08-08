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

| `--format` | Target | Notes |
|---|---|---|
| `canonical-jsonl` | Knovaryn canonical JSONL | Round-trip lossless form of the version; carries evidence refs and metadata. |
| `parquet` | Apache Parquet | Columnar, good for analysis and large corpora; requires the `parquet` extra. |
| `trl-conversational` | TRL / HF `trl` conversational messages | SFT + DPO `conversational`/`text` format; requires `hub` for HF targets. |
| `llamafactory-sharegpt` | LLaMA-Factory ShareGPT | `conversations`-style JSONL used by LLaMA-Factory. |
| `openai-chat` | OpenAI chat messages | `messages`-array training JSONL. |
| `sharegpt` | ShareGPT | Generic ShareGPT-style JSONL (separate from the LLaMA-Factory variant). |
| `alpaca` | Alpaca | Alpaca-style `instruction/input/output` JSON. |
| `huggingface` | Hugging Face Hub | Push a version to the Hub (requires `hub` extra and an approved/verifiable public path). |

`exports.formats` defaults to `[canonical-jsonl, parquet, trl-conversational,
llamafactory-sharegpt]`. Other adapters (`openai-chat`, `sharegpt`, `alpaca`,
`huggingface`) are selectable on the same canonical version.

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
│   ├── train.parquet  valid.parquet  test.parquet
│   ├── trl-conversational.jsonl
│   ├── llamafactory-sharegpt.jsonl
│   └── ... (per selected format)
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
