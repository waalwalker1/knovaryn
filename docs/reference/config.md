# Reference — Configuration

Knovaryn configuration is immutable once resolved. Values come from (highest to
lowest precedence): **admin policy > request > project > user > env >
defaults**. Project config **cannot weaken** admin-enforced security/retention
policy, and protected keys (`sources.url_ingestion`, `storage.database_url`)
are admin-only.

`${ENV_VAR}` placeholders are resolved from the environment (prefix
`KNOVARYN_`). The CLI prints where each value came from via
`knovaryn config validate` (value provenance).

Default config file: `knovaryn.yaml`. State dir: `.knovaryn/`.

## Core

| Key | Default | Meaning |
|---|---|---|
| `schema_version` | `"1.0"` | Config schema version. |
| `project.name` | `"Knovaryn Project"` | Default project display name. |
| `project.description` | `""` | Default project description. |
| `profile` | `"balanced"` | Active profile (`offline-demo`, `fast-local`, `balanced`, `high-quality`, `air-gapped`, `enterprise`). |

## Sources

| Key | Default | Meaning |
|---|---|---|
| `sources.allowed_roots` | `["./data/input"]` | Root directories file intake may read from. |
| `sources.url_ingestion` | `false` | Enable URL source ingestion (admin-protected; SSRF-hardened). |
| `sources.max_file_mb` | `200` | Max source file size. |
| `sources.max_pages` | `1500` | Max pages/sheets. |
| `sources.follow_symlinks` | `false` | Follow symlinks during intake (off for safety). |

## Storage

| Key | Default | Meaning |
|---|---|---|
| `storage.database_url` | `"sqlite+aiosqlite:///./.knovaryn/knovaryn.db"` | DB URL (SQLite default; PostgreSQL `postgresql+asyncpg://...` for team). |
| `storage.artifact_backend` | `"local"` | Artifact backend: `local` or `s3` (S3-compatible). |
| `storage.artifact_root` | `"./.knovaryn/artifacts"` | Local CAS root. |

## Parsing (Docling)

| Key | Default | Meaning |
|---|---|---|
| `parsing.engine` | `"docling"` | Parser. Falls back to a safe text/markdown adapter if the `docling` extra is absent. |
| `parsing.ocr_mode` / `ocr_engine` / `accelerator` | `"auto"` | Docling OCR and accelerator selection (version-aware, validated). |
| `parsing.threads` | `"auto"` | Parser concurrency. |
| `parsing.retain_page_images` | `"sampled"` | Page-image retention policy. |
| `parsing.worker_recycle_documents` | `25` | Recycle worker after N documents (memory guard). |

## Chunking

| Key | Default | Meaning |
|---|---|---|
| `chunking.engine` | `"structure_aware"` | Chunker: `structure_aware` (default) or `docetl_gather` (needs `docetl` extra). |
| `chunking.target_tokens` | `900` | Target chunk length. |
| `chunking.min_tokens` / `max_tokens` | `180` / `1400` | Chunk length bounds. |
| `chunking.neighbor_context_tokens` | `350` | Neighbor context included. |
| `chunking.keep_tables_together` / `keep_lists_together` | `true` | Preserve structural units in one chunk. |

## Planning

| Key | Default | Meaning |
|---|---|---|
| `planning.topologies` | `[sft, preference, evaluation]` | Active topologies (`sft`, `preference`, `kto`, `evaluation`). |
| `planning.task_families` | weighted map | Target mix (e.g. `factual_explanation` 0.25, `procedure` 0.20, …). |
| `planning.difficulty` | `{basic .25, intermediate .50, advanced .25}` | Difficulty distribution. |
| `planning.target_examples` | `2000` | Target example count. |
| `planning.split` | `{grouped_random, train .80, validation .10, test .10, seed 42}` | Source-group-aware split policy. |

## Models

| Key | Default | Meaning |
|---|---|---|
| `models.profile` | `"balanced"` | Model profile (e.g. `deepseek_flash_budget` reference). |
| `models.provider_base_url` | `${KNOVARYN_DEEPSEEK_BASE_URL}` | Provider base URL (OpenAI-compatible). |
| `models.generator` / `critic` / `verifier` | `${KNOVARYN_*_MODEL}` | Generation/critique/verification models + temperature/max tokens. |
| `models.embedding` | `${KNOVARYN_EMBEDDING_MODEL}` | Embedding model. |

The default is the deterministic **fake provider**; real providers
(OpenAI-compatible, Anthropic, DeepSeek) are selectable and opt-in.

## Quality

| Key | Default | Meaning |
|---|---|---|
| `quality.policy` | `"balanced-v1"` | Acceptance policy version. |
| `quality.minimum_overall` | `0.82` | Overall quality floor. |
| `quality.minimum_grounding` | `0.90` | Grounding floor. |
| `quality.require_evidence` | `true` | Require source-span evidence (provenance minimum). |
| `quality.judge_disagreement` | `"review"` | On judge disagreement, route to review (not auto-accept). |
| `quality.human_review_sample` | `0.05` | Fraction of examples routed to human review. |

## Preference

| Key | Default | Meaning |
|---|---|---|
| `preference.negative_strategy` | `"edit_chosen_near_miss"` | How rejected responses are produced (controlled negative). |
| `preference.length_ratio_min` / `max` | `0.80` / `1.25` | Chosen/rejected length-ratio band. |
| `preference.detect_superficial_artifacts` | `true` | Enforce artifact separability checks. |

## Privacy, licensing, budget

| Key | Default | Meaning |
|---|---|---|
| `privacy.provider_data_allowed` | `true` | Allow provider data sharing. |
| `privacy.store_raw_prompts` | `true` | Store raw prompts. |
| `privacy.detect_pii` | `true` | Enable PII detection. |
| `privacy.high_confidence_pii_action` | `"quarantine"` | Action on high-confidence PII. |
| `privacy.retention_days` | `90` | Retention window. |
| `licensing.unknown_license_action` | `"review"` | Unknown licenses go to review, never auto-allowed. |
| `licensing.public_export_requires_approved_sources` | `true` | Public export only from `allowed` sources. |
| `budget.maximum_cost_usd` | `50.0` | Hard cost cap. |
| `budget.maximum_calls` | `10000` | Hard call cap. |
| `budget.maximum_examples` | `2500` | Hard example cap. |

## Exports and telemetry

| Key | Default | Meaning |
|---|---|---|
| `exports.formats` | `[canonical-jsonl, parquet, trl-conversational, llamafactory-sharegpt]` | Export formats (see [exporters](exporters.md)). |
| `exports.include_private_audit_metadata` | `false` | Include private audit metadata in exports (off by default). |
| `telemetry.content_in_logs` | `false` | Write content to logs (off by default). |
| `telemetry.opentelemetry` | `false` | OpenTelemetry export. |
| `telemetry.metrics` | `true` | Internal metrics. |

## Precedence and provenance

Configuration is resolved defaults → user/project config files → admin policy →
env (`KNOVARYN_*`) → request overrides, then validated. `knovaryn config
validate` prints `value_provenance()` for each key so you can see which source
set it — useful when a value is not what you expected.
