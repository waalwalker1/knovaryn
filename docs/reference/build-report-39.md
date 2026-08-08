# Knovaryn Build Report

> Section 39 final implementation report — honest status. Written 2026-08-08.

## 1. Outcome

- **Overall status: PARTIAL** — core pipeline, workspace control plane, MCP tool suite, REST
  plane, license gate, and offline tests are verified green, but the engineering-quality gates
  (`ruff`, `mypy`) are **red on the shipped baseline**, there is no Alembic migration set, and
  the project-wide lint/type debt is not fully resolved.
- Repository path: `.../MircoApps/Omnitrain MCP/knovaryn` (commit to GitHub `waalwalker1/knovaryn`).
- Implemented version: `0.1.0`.
- Commit(s): prior commits `4cd88c3`, `30fcc38`, `26fd9c6`, `66a1d7c` (recovery of OneDrive-dehydrated files, lockfile regeneration). New work in this revision is uncommitted and staged for commit + push.

## 2. What was built

Standing implementation (verified to exist):

- **Domain model** — `src/knovaryn/domain/{schemas,ids,policies,hashing,errors,config,ports}.py`.
- **Durable job engine** — `src/knovaryn/pipeline/jobs/{engine,state,retry,budget,worker}.py`.
- **Pipeline** — `application/service.py`, `pipeline/{planner,split,generate,quality/*,export/*}.py`,
  `infrastructure/{chunking,docling,docetl,intake,exporters,privacy,validation,publish,artifacts,resources}.py`.
- **Observability/security** — `infrastructure/{telemetry,auth,models/*}`.
- **Interfaces** — `interfaces/{cli,mcp,rest}`.

Built in this revision (highest-value missing subsystems):

- **`application/workspace.py`** (new) — project/source registry + durable pipeline jobs +
  validate/version/export/publish, all backed by a real SQLite store and the fake provider.
- **`interfaces/mcp/server.py`** (rewritten) — the full **17-tool** MCP suite from §17.2 on top
  of `Workspace` (create/list project, add/inspect source, estimate, start/get/run/cancel/resume
  job, preview/review example, validate, version, export, publish, compare, doctor).
- **`interfaces/rest/app.py`** (rewritten) — REST control plane + web-console dashboard, bearer-guarded.
- **`pipeline/license.py`** (new) — source license registry + §15.6 publication gate, wired into
  publish and inspect.
- **`infrastructure/models/profiles.py`** (new) + **`litellm_provider.py`** (new) — DeepSeek-V4-Flash
  dated budget profile and the opt-in live LiteLLM/HTTP provider (§11).

## 3. Architecture and dependency decisions

- **Executor / compatible-API result:** Claude Code driving a DeepSeek-V4-Flash-compatible model
  (`deepinfra/deepseek-v4-flash-0731`). Standard text and tool use worked; no reliance on MCP
  plugins, image/document blocks, or other flagged DeepSeek compatibility gaps.
- **Build-model fallback:** none used.
- **API usage/cost:** provider did not expose sufficient usage data for a reliable figure; not reported.
- **MCP/FastMCP:** FastMCP adapter isolated behind `interfaces/mcp/`; stdio stream not executed in
  this environment (mcp extra not installed in the CI venv).
- **Docling:** optional; `docling/adapter.py` + `guard.py` follow current APIs (§2.4, §2.5); not core.
- **DocETL:** optional adapter only (§2.6, §10.4).
- **LiteLLM/provider strategy:** real provider is opt-in behind `deepseek_flash_budget`
  (`profiles.py` → `litellm_provider.py`); offline/CI stay on the deterministic `FakeProvider` (exec rule 2). No prices are treated as permanent (dated `PriceProfile`).
- **Database/artifact:** SQLAlchemy 2.x async over SQLite (WAL); schema created via `create_all`
  (no Alembic migration set — see §9). Local artifact store (`artifacts/local.py`); S3 stub.
- **Important ADRs:** `docs/adr/0001…0006` (dependency baseline, MCP/FastMCP, docling guard,
  docetl, litellm/providers, storage). ADR 0005 records the dated-price discipline.

## 4. Validation executed

| Command | Result | Notes |
|---|---:|---|
| `uv run pytest -q -p no:cacheprovider` (9 test files) | ✅ 38 passed | offline, deterministic fake provider; from stable export `/tmp/knovaryn_ci` |
| workspace control plane (workspace tests ×5) | ✅ | create→source→job→run→validate→version→export→publish(dry-run) |
| license report + publication gate tests | ✅ | MIT=allowed, none=review, cc-by-nd=blocked; gate blocks unresolved |
| REST control plane (TestClient tests ×3) | ✅ | full lifecycle over HTTP |
| MCP module import + tool presence | ✅ | all 17 spec tools present; module imports clean |
| deepseek profile + gateway build | ✅ | `build_gateway('deepseek_flash_budget')` = `ModelGateway(LiteLLMProvider)` |
| `ruff check src tests` | 🔶 **RED** | ~400 style violations (mostly E501), pre-existing baseline |
| `ruff format --check src tests` | 🔶 **RED** | not green on baseline |
| `mypy src` | 🔶 **RED** | 79 errors / 27 files, incl. pre-existing `service.py`, `gateway.py` |
| CLI doctor (offline) | ✅ | `knovaryn doctor` health checks |
| offline demo pipeline | ✅ | runs end-to-end under fake provider |
| container build / migration / clean-install | 🔶 not executed here | Dockerfile present; GitHub CI not run against this revision |

## 5. Test and benchmark facts

- **38 tests pass** offline under the fake provider: `test_chunking`, `test_export`,
  `test_identity`, `test_intake_adversarial`, `test_pricing`, `test_split`, `test_validators`,
  `test_rest_api`, `test_workspace_control`.
- No performance benchmark numbers were measured in this environment; `docs/marketing/benchmark-methodology.md`
  documents methodology only (§2.9: research numbers are not acceptance criteria).

## 6. Security and governance checks

- **Threat model:** `docs/security/threat-model.md` present; §15 licensing + §23 controls implemented
  (license gate, PII scanners, bearer guard, state-handle auth, adversarial-intake fixture).
- **Outstanding findings:** ruff/mypy lint-type debt (see §9).
- **Dependency/secret scan:** not run in this session (no credentials available).
- **SBOM/signing readiness:** not yet configured.
- **Name-clearance:** canonical identity `knovaryn` / server id `knovaryn_mcp` enforced via `identity.py`
  (`tests/test_identity.py`); no OmniTrain-branded product surface (see §39.1).

## 7. Exact quickstart

Executed successfully (offline):

```bash
uv sync --extra dev
uv run pytest -q -p no:cacheprovider          # 38 passed
uv run knovaryn doctor --json || echo "exit 1 = missing extras acceptable"
uv run knovaryn server                        # REST + web console at http://127.0.0.1:<port>
```

REST control-plane flow exercised via `tests/test_rest_api.py`:
`POST /v1/projects` → `POST /v1/projects/{id}/sources` → `POST /v1/projects/{id}/pipeline` →
`POST /v1/jobs/{id}/run` → `GET /v1/projects/{id}/examples` → `POST /v1/projects/{id}/export` →
`POST /v1/projects/{id}/publish` (dry-run).

## 8. Credentials-dependent paths

Fully implemented but **not live-tested** (no credentials/network in this environment):

- **DeepSeek live generation** — `profiles.py` → `LiteLLMProvider.complete()` (LiteLLM or direct
  OpenAI-compatible HTTP); requires `KNOVARYN_DEEPSEEK_API_KEY` / `KNOVARYN_DEEPSEEK_BASE_URL`.
- **HF publication** — `infrastructure/publish/hf.py`; requires a `huggingface-hub` token.
- **Docling/DocETL live document ingestion** — optional extras, not exercised.

## 9. Known limitations

- **Lint/type gates are red on the shipped baseline** — `ruff check` (~400 violations, mostly E501)
  and `mypy src` (79 errors/27 files) were not passing before this revision and remain open.
  My new interface modules are largely cleaned (`rest/app.py` mypy-clean; `mcp/server.py` only the
  optional-`mcp` import). Tracked as follow-up, not silently marked green (see `BUILD_LEDGER.md` §26/§36).
- **No Alembic migration set** — `alembic` is declared but there is no `migrations/` dir; schema is
  created via `create_all`. Adding a migration baseline is required before a production DB.
- **Docling golden corpus not re-run in this environment** — adapter/guard exist; the full document
  corpus verification was not executed here (OneDrive churn; see VALIDATION_LOG Phase P).
- **MCP stdio / Streamable-HTTP transport not executed** — the `mcp` extra is not installed in the
  CI venv; `build_server()` raises `ConfigurationError` when `mcp` is absent (by design).
- **Web console is a route on the REST app** (`/`), not a separate `interfaces/web/` module.
- **Review/relabel persistence** in the workspace MCP path records an audit event but does not yet
  rewrite an example's quality flags (optimistic concurrency noted in the tool docstring).

## 10. Deliverable index

- README: `README.md`
- Docs: `docs/**` (concepts, architecture, guides, reference, security, marketing, peers, ADRs)
- Config: `src/knovaryn/domain/config.py`, `docs/reference/config.md`
- CLI: `src/knovaryn/interfaces/cli/`, `docs/reference/cli.md`
- REST API + web console: `src/knovaryn/interfaces/rest/app.py`
- MCP tools: `src/knovaryn/interfaces/mcp/server.py`
- License/publication gate: `src/knovaryn/pipeline/license.py`
- Governance/OSS: `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `GOVERNANCE.md`, `SECURITY.md`, `SUPPORT.md`, `MAINTAINERS.md`
- Marketing/launch: `docs/marketing/*`, `ROADMAP.md`
- Validation/ledger: `VALIDATION_LOG.md`, `BUILD_LEDGER.md`, `SPEC_INDEX.md`, `DECISION_LOG.md`
