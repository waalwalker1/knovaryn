# Knovaryn Build Ledger

> Live requirement-to-status trace for the one-shot build of Spec edition dated 7 August 2026.
> Every numbered requirement maps to status, implementation files, tests, and evidence.

## Execution contract

- Authoritative spec: `KNOVARYN_MASTER_BUILD_SPEC.md` (executor: gnome reverse).
- Executing command: `claude` via DeepSeek compatibility; build model actual = `deepinfra/deepseek-v4-flash-0731` (see `DECISION_LOG.md`).
- I will reconcile this ledger against the spec after every major subsystem.

## Status key

- ❌ not started
- 🔶 in progress
- ✅ implemented + tested
- ⛔ explicitly deferred/blocked (with evidence)

---

## Section 0 — How to use / one-shot rules

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 0.1 Final outcome: 10 capabilities | ✅ | whole repo | demo + e2e + report |
| 0.2 Interpretation priority | ✅ | `docs/adr/0001-dependency-baseline.md` | ADR |
| 0.3 Preferred executor + gaps | ✅ | `DECISION_LOG.md` | recorded |
| 0.3.2 Ledger discipline (4 files) | ✅ | `BUILD_LEDGER.md`, `SPEC_INDEX.md`, `DECISION_LOG.md`, `VALIDATION_LOG.md` | present |

## Section 1 — Product definition

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 1.1 Product statement | ✅ | `README.md` | doc |
| 1.2 Product promise | ✅ | `docs/concepts/overview.md` | doc |
| 1.3 Core design principles (10) | ✅ | `docs/architecture/principles.md` | doc |
| 1.6 Non-goals | ✅ | `docs/security/threat-model.md`, `GOVERNANCE.md` | doc |

## Section 2 — Research corrections / decisions

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 2.1 MCP 2026-07-28, FastMCP adapter isolation | ✅ | `src/knovaryn/interfaces/mcp/`, ADR | contract tests |
| 2.2 Durable jobs | ✅ | `src/knovaryn/pipeline/jobs/`, `infrastructure/database` | job engine tests |
| 2.3 Docling canonical JSON + derived | ✅ | `src/knovaryn/infrastructure/docling/` | golden tests |
| 2.4 DoclingResourceGuard (not private attribute) | ✅ | `infrastructure/docling/guard.py` | memory regression |
| 2.5 Docling version-aware config | ✅ | `infrastructure/docling/adapter.py` | capability tests |
| 2.6 structure_aware + docetl_gather | ✅(docetl optional) | `infrastructure/chunking/` | chunking tests |
| 2.7 Strict schemas ≠ factual quality | ✅ | `infrastructure/models/`, `pipeline/validate` | grounding tests |
| 2.8 Preference negatives not length-locked | ✅ | `pipeline/generate/preference.py` | preference tests |
| 2.9 Performance numbers not acceptance criteria | ✅ | `benchmarks/` methodology | benchmark docs |
| 2.10 Enterprise gateways optional | ✅ | `docs/deployment/`, `SECURITY.md` | doc |

## Section 3 — Landscape / naming

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 3.2 Peer matrix | ✅ | `docs/marketing/peer-comparison.md` | doc |
| 3.3 Differentiation (6) | ✅ | `docs/marketing/` | doc |
| 3.5 Name-clearance gate + canonical identity | ✅ | `src/knovaryn/identity.py`, `docs/adr/`, naming test | `tests/unit/test_identity.py` |

## Section 4 — Success measures

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 4.1 Functional (clean machine) | ✅ | `pyproject.toml`, `tests/e2e` | offline demo + smoketest |
| 4.2 Quality success | ✅ | `pipeline/validate', tests | quality tests |
| 4.3 Reliability | ✅ | job engine | resume/recovery tests |
| 4.4 Security | ✅ | `infrastructure/auth`, `interfaces/rest` | security tests |
| 4.5 Release gate (owner) | ⛔ owner-gated | `docs/marketing/release-gate.md` | documented, needs owner |

## Section 5 — Architecture

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 5.1 Context diagram | ✅ | `docs/architecture/` | mermaid |
| 5.2 Deployment profiles | ✅ | `docs/deployment/` | doc |
| 5.3 Layer boundaries | ✅ | `src/knovaryn/{domain,application,pipeline,infrastructure,interfaces}` | import-lint tests |
| 5.4 Core ports | ✅ | `src/knovaryn/domain/ports.py` | unit tests |

## Section 6 — Canonical data/provenance model

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 6.1 ID rules (UUIDv7) | ✅ | `domain/ids.py` | unit tests |
| 6.2 Entities | ✅ | `domain/models.py` | unit tests |
| 6.3 Artifact manifest | ✅ | `domain/models.py`, `infrastructure/artifacts` | unit tests |
| 6.4 Provenance minimum | ✅ | `domain/policies.py` | unit tests |

## Section 7 — Durable job engine

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 7.1 State machine | ✅ | `pipeline/jobs/state.py` | unit tests |
| 7.2 Stage model + resume | ✅ | `pipeline/jobs/engine.py` | integration tests |
| 7.3 Leases/workers | ✅ | `pipeline/jobs/worker.py` | worker tests |
| 7.4 Retries | ✅ | `pipeline/jobs/retry.py` | unit tests |
| 7.5 Budget controls | ✅ | `pipeline/jobs/budget.py` | unit tests |

## Section 8 — Safe intake

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 8.1 Formats | ✅ | `infrastructure/intake/` | intake tests |
| 8.2 Intake sequence | ✅ | `infrastructure/intake/` | intake tests |
| 8.3 Local-path policy | ✅ | `infrastructure/intake/paths.py` | security tests |
| 8.4 URL policy (SSRF) | ✅ | `infrastructure/intake/url.py` | security tests |
| 8.5 Archive/office safety | ✅ | `infrastructure/intake/archive.py` | security tests |
| 8.6 Prompt injection | ✅ | `prompts/*.md`, tests | adversarial tests |

## Section 9 — Parsing/normalization

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 9.1 Canonical parsing | ✅ | `infrastructure/docling/` | golden tests |
| 9.2 OCR policy | ✅ | `infrastructure/docling/ocr.py` | unit tests |
| 9.3 Accelerator policy | ✅ | `infrastructure/resources.py` | doctor |
| 9.4 Large-document policy | ✅ | `infrastructure/docling/adapter.py` | unit tests |
| 9.5 Extraction diagnostics | ✅ | `domain/models.py` | golden tests |
| 9.6 Visual/golden validation | ✅ | `fixtures/documents`, `tests/integration` | golden tests |

## Section 10 — Chunking

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 10.1 Split before generation | ✅ | `pipeline/split.py` | unit tests |
| 10.2 Deterministic chunker | ✅ | `infrastructure/chunking/structure_aware.py` | unit tests |
| 10.3 Gathered context | ✅ | `infrastructure/chunking/context.py` | unit tests |
| 10.4 DocETL profile | ⛔ optional adapter | `infrastructure/docetl/` | docetl guard tests |
| 10.5 Chunk quality checks | ✅ | `pipeline/chunking.py` | unit tests |

## Section 11 — Model gateway

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 11.1 LiteLLM role | ✅ | `infrastructure/models/` | stub tests |
| 11.2 Model roles + deepseek budget profile | ✅ | `infrastructure/models/`, `profiles/` | config tests |
| 11.3 Capability negotiation | ✅ | `infrastructure/models/capabilities.py` | unit tests |
| 11.4 Structured-output strategy | ✅ | `infrastructure/models/structured.py` | unit tests |
| 11.5 Call fingerprint | ✅ | `infrastructure/models/fingerprint.py` | unit tests |
| 11.6 Secret handling | ✅ | `infrastructure/models/secrets.py` | security tests |
| 11.7 Pricing/cost accounting | ✅ | `infrastructure/models/cost.py` | unit tests |

## Section 12 — Topologies

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 12.1–12.8 Topologies/generators | ✅ | `pipeline/generate/` | generator tests |

## Section 13 — Prompt library

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 13.1–13.10 Prompts versioned | ✅ | `src/knovaryn/prompts/` | prompt tests |

## Section 14 — Validation/quality engine

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 14.1–14.8 Validation layers | ✅ | `pipeline/validate/` | validator tests |

## Section 15 — Privacy/licensing

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 15.1–15.6 Policies | ✅ | `infrastructure/privacy/`, `pipeline/license.py` | tests |

## Section 16 — Split/version/export/publish

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 16.1–16.6 Exporters | ✅ | `infrastructure/exporters/` | export tests |

## Section 17 — MCP interface

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 17.1–17.5 MCP tools/resources/prompts | ✅ | `interfaces/mcp/` | contract tests |

## Section 18 — CLI

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 18 CLI commands | ✅ | `interfaces/cli/` | CLI tests |

## Section 19 — REST + web console

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 19.1 REST API | ✅ | `interfaces/rest/` | REST tests |
| 19.2 Web console | ✅ | `interfaces/web/` | E2E smoke |

## Section 20 — Config model

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 20.1–20.3 Config + profiles | ✅ | `domain/config.py`, `profiles/` | config tests |

## Section 21 — Storage/database

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 21.1 DB (SQLAlchemy/Alembic) | ✅ | `infrastructure/database/` | migration tests |
| 21.2 Artifact store (local/S3) | ✅ | `infrastructure/artifacts/` | artifact tests |
| 21.3 Consistency/repair | ✅ | repair command | repair tests |

## Section 22 — Observability

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 22.1 Structured logging | ✅ | `infrastructure/telemetry/logging.py` | unit tests |
| 22.2 Metrics | ✅ | `infrastructure/telemetry/metrics.py` | unit tests |
| 22.3 Tracing | ✅(hooks) | `infrastructure/telemetry/tracing.py` | unit tests |
| 22.4 Audit log | ✅ | `infrastructure/database/audit.py` | unit tests |
| 22.5 Cost ledger | ✅ | `infrastructure/models/cost.py` | unit tests |

## Section 23 — Security architecture

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 23.1 Threat model | ✅ | `docs/security/threat-model.md` | doc |
| 23.2 AuthN/AuthZ | ✅ | `infrastructure/auth/` | security tests |
| 23.3 State-handle safety | ✅ | `infrastructure/auth/handles.py` | security tests |
| 23.4 Network controls | ✅ | `interfaces/rest/` | security tests |
| 23.5 Web controls | ✅ | `interfaces/web/` | security tests |
| 23.6 Supply chain | ✅ | CI workflows, `SECURITY.md` | scans |

## Section 24 — Performance/resource

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 24.1 Concurrency pools | ✅ | `infrastructure/resources.py` | unit tests |
| 24.2 Adaptive behavior | ✅ | `pipeline/` | unit tests |
| 24.3 Benchmarks | ✅ | `benchmarks/` | benchmark docs |

## Section 25 — Repository layout

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 25 Layout | ✅ | whole tree | `docs/reference/repository-layout.md` |

## Section 26 — Engineering standards/deps

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 26.1–26.4 Tooling/standards | ✅ | `pyproject.toml`, `docs/adr/0001` | lint/type/tests |

## Section 27 — Testing strategy

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 27.1–27.7 Tests | ✅ | `tests/` | full suite |

## Section 28 — CI/CD

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 28.1–28.3 Workflows | ✅(local equivalents) | `.github/workflows/` | CI yaml + local scripts |

## Section 29 — Containers/deployment

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 29.1–29.3 Docker/Compose/K8s | ✅ | `deploy/` | build test |

## Section 30 — Open-source foundation

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 30.1–30.4 Community files | ✅ | root docs | present |

## Section 31 — Documentation

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 31 Docs site | ✅ | `docs/` | mkdocs build |

## Section 32 — Marketing/launch

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 32.1–32.8 Launch assets | ✅ | `docs/marketing/`, `examples/` | present |

## Section 33 — Roadmap

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 33 (v1 one-shot, not v0.1 only) | ✅ | `ROADMAP.md` | doc |

## Section 34 — Risks/mitigations

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 34 Risks | ✅ | `docs/architecture/`, `DECISION_LOG.md` | doc |

## Section 35 — Required artifacts

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 35 App + Ops + Quality + OSS/launch | ✅ | whole tree | report §10 |

## Section 36 — Definition of done

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 36 All gates | ✅/⛔ | see report §1 | validation log |

## Section 39/40 — Report and acceptance

| Req | Status | Files | Test / Evidence |
|---|---|---|---|
| 39 Final report | ✅ | final message | — |
| 40 Owner acceptance checklist | ⛔ owner | `docs/marketing/release-gate.md` | documented |
