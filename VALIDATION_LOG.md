# Knovaryn Validation Log (VALIDATION_LOG.md)

Every command actually run, its result, failures, fixes, and final reruns.
Update after each major phase. Final section = full suite results.

## Phase A — toolchain bootstrap

- [x] Python version discovered: `3.13` (venv at `.venv`, `requires-python >=3.11`)
- [x] Packaging tool: `uv` (`/Users/dhananjay/.local/bin/uv`)
- [x] Project venv created; runtime deps installed via `uv sync`
- [x] Dev test tooling installed into venv: `pytest 9.1.1`, `pytest-asyncio 1.4.0` (via `uv pip install --python .venv/bin/python`)

## Phase B..N — subsystem tests

### Validators / acceptance policy (spec §13, §14)

Diagnostic (`/private/tmp/knovaryn_debug.py`) — single representative SFT example:

| Run | GROUNDING | COMPLETE | FORMAT | REFUSAL | ARTIFACT | OVERALL | Notes |
|---|---:|---:|---:|---:|---:|---:|---|
| Before fix | 0.833 | 1.0 | 1.0 | 1.0 | 1.0 | rejected (`grounding<0.9`) | punctuation tokens `material:`, `source.` bypassed stopword & evidence match |
| After fix | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | **accepted** | `_fractional_overlap` now strips non-alphanumerics per token |

**Defect found & fixed:** `normalize_text` keeps punctuation, so stopword matching
(`material:`, `source.`) and evidence overlap failed. Fixed in
`src/knovaryn/pipeline/quality/validators.py` (`_strip_non_alpha` + `_lexical`).

### End-to-end offline pipeline (deterministic fake provider)

`/private/tmp/knovaryn_e2e_check.py` (2 demo sources, grouped_random split):

| Metric | Value |
|---|---:|
| parsed documents | 2 |
| chunks | 9 |
| candidates generated | 5 |
| accepted | 5 |
| acceptance rate | 1.0 |
| mean overall | 1.0 |
| release SHA-256 | present (64 hex) |
| release bundle bytes | >0 |

**Defect found & fixed:** release zip contained a duplicate `manifest.json`
(added to both `self.manifest` and `self.files`). Fixed in
`src/knovaryn/pipeline/export/release.py` — manifest is written only from
`self.manifest` in `to_zip()`. Re-run produced no `Duplicate name` warning.

### Full unit/integration suite

Command: `.venv/bin/python -m pytest tests/test_export.py tests/test_validators.py tests/test_identity.py tests/test_split.py tests/test_intake_adversarial.py tests/test_chunking.py tests/test_pricing.py -q -p no:cacheprovider`

| Result | Notes |
|---|---:|
| **30 passed in 119.49s (0:01:59)** | all green |

### Interfaces (CLI / REST / MCP / web console)

See interface import check (task ledger) — CLI/REST/MCP/web modules import
cleanly with optional heavy deps guarded.

## Phase O — final validation

| Command | Result | Notes |
|---|---:|---|
| debug validator script (venv) | OVERALL accepted 1.0 | grounding fix verified |
| e2e offline pipeline (venv) | PIPELINE OK (5/5 accepted) | release bundle + SHA verified, no dup manifest |
| `pytest` (7 test files) | 30 passed | full unit/integration suite green |
| interface import check | CLI/REST/MCP/WEB import | see task ledger |

## Phase P — build-gaps revision (2026-08-08, honest re-baseline)

Rebuilt high-value missing subsystems on the persisted workspace, then re-ran the full
suite from a stable git-archive export (`/tmp/knovaryn_ci`) to avoid OneDrive churn.

| Command | Result | Notes |
|---|---:|---|
| `uv run pytest -q -p no:cacheprovider` (9 test files) | **38 passed** | includes new `test_workspace_control.py` (5) + `test_rest_api.py` (3) |
| workspace control-plane lifecycle | ✅ create→source→job→run→validate→version→export→publish(dry-run) | real SQLite, offline fake provider |
| license report + publication gate | ✅ MIT=allowed, none=review, cc-by-nd=blocked; gate blocks on unresolved | `tests: test_license_report_and_publication_gate`, `test_publish_blocked_on_unapproved_source` |
| REST control plane (TestClient) | ✅ full lifecycle over HTTP | `tests/test_rest_api.py` |
| MCP tool suite | ✅ all 17 spec tools present; module imports clean | `interfaces/mcp/server.py` |
| deepseek budget profile + live provider | ✅ gateway builds `LiteLLMProvider`; config accepts profile | `profiles.py`, `litellm_provider.py` |

Honest remaining gate status (NOT green, pre-existing on baseline):

| Gate | Result | Scope |
|---|---:|---|
| `ruff check src tests` | 🔶 ~400 style violations (mostly E501) | pre-existing across tree; new files largely formatted |
| `ruff format --check src tests` | 🔶 not green | pre-existing baseline |
| `mypy src` | 🔶 79 errors / 27 files | includes pre-existing `service.py`, `gateway.py`; new interface modules mostly clean |
| Alembic migrations | 🔶 no `migrations/` dir exists despite `alembic` dep | schema via SQLAlchemy `create_all` only |

These gates are reported honestly in `BUILD_LEDGER.md` (§26/§36 + Gates table) and are **not**
marked as passing. Fixing the full lint/type baseline is tracked as open follow-up work.

## Phase Q — gates green + migration baseline (2026-08-09 follow-up)

The open lint/type baseline and the missing migration baseline (both flagged 🔶 in
Phase P) were closed in a follow-up revision. Every command below was actually run.

| Command | Result | Notes |
|---|---:|---|
| `uv run ruff check src tests` | ✅ "All checks passed!" | lint gate green (was 🔶, ~400 E501) |
| `uv run ruff format --check src tests` | ✅ 100 files already formatted | format gate green (was 🔶) |
| `uv run mypy src/knovaryn` | ✅ "Success: no issues found in 91 source files" | type gate green (was 🔶, 79 errors/27 files) |
| `uv run pytest -m "not live"` | ✅ **48 passed** | was 38; +3 migration, +7 artifact-store tests |
| `alembic upgrade head` (fresh SQLite) | ✅ upgrade 7373f061034e ran | migrations/ + alembic.ini added |
| `alembic check` (after upgrade) | ✅ "No new upgrade operations detected" | baseline exactly matches ORM metadata (no drift) |
| `alembic downgrade base` | ✅ reversed; only `alembic_version` remains | migration reversible (§21.1) |
| `uv run mkdocs build` | ✅ "Documentation built in 0.42 seconds" | `mkdocs.yml` added (was missing → `make docs-build` failed) |
| `uv build` | ✅ `knovaryn-0.1.0.tar.gz` + `-py3-none-any.whl` | wheel + sdist build clean |
| Clean-install smoke (fresh venv, no extras) | ✅ | wheel installs; `knovaryn --help`, `doctor --json`, `version` work |
| Offline `demo --examples 3 --json` (clean venv) | ✅ 2 parsed → 10 chunks → 7 SFT accepted | release.zip + result.json; **no API keys** required |
| `benchmarks/bench_pipeline.py` | ✅ **1107.85 examples/s** (0.005 s, 2 src → 5 accepted) | §24.3 offline framework cost |

New test files (all green):

- `tests/test_migrations.py` — 3 tests: full metadata schema after `upgrade head`,
  no autogenerate drift vs models, `downgrade base` reversible.
- `tests/test_artifact_store.py` — 7 tests: put/get round-trip, content dedup,
  corruption detection, missing-artifact NotFound, manifest metadata, streaming.

Honest notes carried forward (not credentials-dependent but outside this env):

- Docling/DocETL/litellm/S3 are opt-in extras not installed here; doctor reports
  them as "not installed" and the offline path does not require them.
- Live paid provider tests are explicitly opt-in and were not run (no credentials).
- GPT/domain checks in CI run on GitHub, not executed against this repo's workflow.

