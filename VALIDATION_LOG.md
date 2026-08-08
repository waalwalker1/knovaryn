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
