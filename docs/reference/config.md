# Reference — Configuration

Knovaryn configuration is immutable once resolved. Values come from (highest to
lowest precedence): **admin policy > request > project > user > env >
defaults**. Project config **cannot weaken** admin-enforced security/retention
policy, and protected keys (`sources.url_ingestion`, `storage.database_url`)
are admin-only.

`${ENV_VAR}` placeholders are resolved from the environment (prefix
`KNOVARYN_`). State dir: `.knovaryn/`. Inspect the resolved values with
`knovaryn doctor --json`, which reports configuration health and provenance
for every section.

## Keys and defaults

<!-- BEGIN GENERATED CONFIG DEFAULTS -->

Defaults generated from `knovaryn.domain.config._DEFAULTS` — the single
authoritative settings source. `${ENV}` placeholders resolve from the
environment (`KNOVARYN_` prefix).

| Key | Default |
|---|---|
| `budget.maximum_calls` | `10000` |
| `budget.maximum_cost_usd` | `50.0` |
| `budget.maximum_examples` | `2500` |
| `chunking.engine` | `"structure_aware"` |
| `chunking.keep_lists_together` | `true` |
| `chunking.keep_tables_together` | `true` |
| `chunking.max_tokens` | `1400` |
| `chunking.min_tokens` | `180` |
| `chunking.neighbor_context_tokens` | `350` |
| `chunking.target_tokens` | `900` |
| `exports.formats` | `["canonical-jsonl", "parquet", "trl-conversational", "llamafactory-sharegpt"]` |
| `exports.include_private_audit_metadata` | `false` |
| `licensing.public_export_requires_approved_sources` | `true` |
| `licensing.unknown_license_action` | `"review"` |
| `models.critic.model` | `"${KNOVARYN_CRITIC_MODEL}"` |
| `models.critic.temperature` | `0.0` |
| `models.embedding.model` | `"${KNOVARYN_EMBEDDING_MODEL}"` |
| `models.generator.max_output_tokens` | `2400` |
| `models.generator.model` | `"${KNOVARYN_GENERATOR_MODEL}"` |
| `models.generator.temperature` | `0.3` |
| `models.profile` | `"balanced"` |
| `models.provider_base_url` | `"${KNOVARYN_DEEPSEEK_BASE_URL}"` |
| `models.verifier.model` | `"${KNOVARYN_VERIFIER_MODEL}"` |
| `models.verifier.temperature` | `0.0` |
| `parsing.accelerator` | `"auto"` |
| `parsing.engine` | `"docling"` |
| `parsing.ocr_engine` | `"auto"` |
| `parsing.ocr_mode` | `"auto"` |
| `parsing.retain_page_images` | `"sampled"` |
| `parsing.threads` | `"auto"` |
| `parsing.worker_recycle_documents` | `25` |
| `planning.difficulty.advanced` | `0.25` |
| `planning.difficulty.basic` | `0.25` |
| `planning.difficulty.intermediate` | `0.5` |
| `planning.split.seed` | `42` |
| `planning.split.strategy` | `"grouped_random"` |
| `planning.split.test` | `0.1` |
| `planning.split.train` | `0.8` |
| `planning.split.validation` | `0.1` |
| `planning.target_examples` | `2000` |
| `planning.task_families.comparison` | `0.15` |
| `planning.task_families.extraction` | `0.1` |
| `planning.task_families.factual_explanation` | `0.25` |
| `planning.task_families.procedure` | `0.2` |
| `planning.task_families.troubleshooting` | `0.2` |
| `planning.task_families.unanswerable` | `0.1` |
| `planning.topologies` | `["sft", "preference", "evaluation"]` |
| `preference.detect_superficial_artifacts` | `true` |
| `preference.length_ratio_max` | `1.25` |
| `preference.length_ratio_min` | `0.8` |
| `preference.negative_strategy` | `"edit_chosen_near_miss"` |
| `preference.profile` | `"heuristic"` |
| `privacy.detect_pii` | `true` |
| `privacy.high_confidence_pii_action` | `"quarantine"` |
| `privacy.provider_data_allowed` | `true` |
| `privacy.retention_days` | `90` |
| `privacy.store_raw_prompts` | `true` |
| `profile` | `"balanced"` |
| `project.description` | `""` |
| `project.name` | `"Knovaryn Project"` |
| `quality.human_review_sample` | `0.05` |
| `quality.judge_disagreement` | `"review"` |
| `quality.minimum_grounding` | `0.9` |
| `quality.minimum_overall` | `0.82` |
| `quality.policy` | `"balanced-v1"` |
| `quality.require_evidence` | `true` |
| `quality.semantic_profile` | `"offline-fast"` |
| `schema_version` | `"1.0"` |
| `server.admin_principals` | `[]` |
| `server.allow_insecure_nonloopback` | `false` |
| `server.api_token` | `""` |
| `server.cors_origins` | `[]` |
| `server.host` | `"127.0.0.1"` |
| `server.port` | `8000` |
| `server.rate_limit.max_concurrent_jobs` | `4` |
| `server.rate_limit.max_provider_calls_per_run` | `0` |
| `server.rate_limit.max_publish_attempts_per_hour` | `10` |
| `server.rate_limit.max_upload_bytes` | `26214400` |
| `server.rate_limit.requests_per_minute` | `600` |
| `sources.allowed_roots` | `["./data/input"]` |
| `sources.follow_symlinks` | `false` |
| `sources.max_file_mb` | `200` |
| `sources.max_pages` | `1500` |
| `sources.url_ingestion` | `false` |
| `storage.artifact_backend` | `"local"` |
| `storage.artifact_root` | `"./.knovaryn/artifacts"` |
| `storage.database_url` | `"sqlite+aiosqlite:///./.knovaryn/knovaryn.db"` |
| `telemetry.content_in_logs` | `false` |
| `telemetry.metrics` | `true` |
| `telemetry.opentelemetry` | `false` |

<!-- END GENERATED CONFIG DEFAULTS -->

## Notes on non-obvious keys

- `parsing.*` — Docling OCR/accelerator selection is version-aware and
  validated at load time; the parser falls back to a safe text/markdown
  adapter when the `docling` extra is absent.
- `chunking.engine: docetl_gather` requires the `docetl` extra
  ([ADR-0004](../adr/0004-docetl-profile.md)).
- `models.*` — the default runtime uses the deterministic **fake provider**;
  real OpenAI-compatible / Anthropic / DeepSeek providers are opt-in
  ([ADR-0005](../adr/0005-litellm-and-providers.md)). Provider keys are never
  accepted through tool arguments.
- `quality.semantic_profile` — `offline-fast` (default, deterministic-only,
  network-free) or `certified-semantic` (adds the cited-evidence-only judge;
  see [validation profiles](profiles.md)).
- `preference.profile` — `heuristic` (default) or `certified-pairwise`
  (adds the two-order evidence-cited judge; see
  [validation profiles](profiles.md)).
- `licensing.unknown_license_action: review` — unknown licenses always route
  to review; they are never auto-allowed for public release.
- `exports.formats` — see [exporters](exporters.md) for the generated,
  authoritative format list.

## Precedence and provenance

Configuration is resolved defaults → user/project config files → admin policy →
env (`KNOVARYN_*`) → request overrides, then validated. `knovaryn doctor`
reports the resolved configuration sections so you can see which source set a
value — useful when a value is not what you expected.
