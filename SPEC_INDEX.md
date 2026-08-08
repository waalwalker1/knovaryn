# Knovaryn Spec Index

Compact section-to-component map of the authoritative master spec.

| Spec § | Title | Primary implementation surface |
|---|---|---|
| 0 | How to use / one-shot rules | Ledger files, `docs/adr/` |
| 1 | Product definition | `README.md`, `docs/concepts/` |
| 2 | Research corrections / decisions | `src/knovaryn/interfaces/mcp/`, jobs, docling guard, chunking |
| 3 | Landscape / naming | `src/knovaryn/identity.py`, `docs/marketing/peer-comparison.md` |
| 4 | Success measures / release gates | `tests/e2e`, `docs/marketing/release-gate.md` |
| 5 | Architecture | `src/knovaryn/{domain,application,pipeline,infrastructure,interfaces}`, `domain/ports.py` |
| 6 | Canonical data / provenance | `src/knovaryn/domain/models.py`, `domain/ids.py`, `domain/policies.py` |
| 7 | Durable job engine | `src/knovaryn/pipeline/jobs/` |
| 8 | Safe intake | `src/knovaryn/infrastructure/intake/` |
| 9 | Parsing / normalization | `src/knovaryn/infrastructure/docling/` |
| 10 | Structure-aware chunking | `src/knovaryn/infrastructure/chunking/`, `pipeline/split.py` |
| 11 | Model gateway / routing | `src/knovaryn/infrastructure/models/`, `profiles/` |
| 12 | Generation topologies | `src/knovaryn/pipeline/generate/` |
| 13 | Prompt library | `src/knovaryn/prompts/` |
| 14 | Validation / quality | `src/knovaryn/pipeline/validate/` |
| 15 | Privacy / licensing | `src/knovaryn/infrastructure/privacy/`, `pipeline/license.py` |
| 16 | Split / version / export / publish | `src/knovaryn/infrastructure/exporters/`, `pipeline/version.py` |
| 17 | MCP interface | `src/knovaryn/interfaces/mcp/` |
| 18 | CLI | `src/knovaryn/interfaces/cli/` |
| 19 | REST + web console | `src/knovaryn/interfaces/{rest,web}/` |
| 20 | Configuration model | `src/knovaryn/domain/config.py`, `profiles/` |
| 21 | Storage / database | `src/knovaryn/infrastructure/database/`, `infrastructure/artifacts/` |
| 22 | Observability / audit / cost | `src/knovaryn/infrastructure/telemetry/`, `infrastructure/models/cost.py` |
| 23 | Security architecture | `src/knovaryn/infrastructure/auth/`, `interfaces/`, `docs/security/` |
| 24 | Performance / resource | `src/knovaryn/infrastructure/resources.py`, `benchmarks/` |
| 25 | Repository layout | whole tree, `docs/reference/repository-layout.md` |
| 26 | Engineering standards / deps | `pyproject.toml`, `docs/adr/0001-dependency-baseline.md` |
| 27 | Testing strategy | `tests/` |
| 28 | CI/CD | `.github/workflows/`, `scripts/ci.sh` |
| 29 | Containers / deployment | `deploy/`, `src/knovaryn/interfaces/cli/commands/server.py` |
| 30 | Open-source foundation | root community files |
| 31 | Documentation | `docs/` (mkdocs) |
| 32 | Marketing / launch | `docs/marketing/` |
| 33 | Roadmap | `ROADMAP.md` |
| 34 | Risks / mitigations | `docs/architecture/`, `DECISION_LOG.md` |
| 35 | Required artifacts | whole tree |
| 36 | Definition of done | `VALIDATION_LOG.md`, final report |
| 37 | Research ledger | `docs/adr/`, `DECISION_LOG.md` |
| 38 | Master one-shot build prompt | executor contract |
| 39 | Final implementation report | final message |
| 40 | Owner acceptance checklist | `docs/marketing/release-gate.md` |
