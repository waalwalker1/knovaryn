# Changelog

All notable changes to Knovaryn are documented here, following the
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. This project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) starting at
v1.0.0; during the `0.x` public-maturity line compatibility is approached but not
yet guaranteed (see [ROADMAP.md](ROADMAP.md)).

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Community and governance files: contributing guide, governance model, support
  boundaries, maintainer roster, roadmap, security and issue templates.
- Public documentation site (MkDocs).
- Alembic migration baseline (`migrations/`, `alembic.ini`) matching the ORM
  metadata "head", verified no-drift and reversible (§21.1).
- Migration-contract tests (`tests/test_migrations.py`) and local CAS artifact
  round-trip tests (`tests/test_artifact_store.py`), §21.2.
- MkDocs site configuration (`mkdocs.yml`) so `make docs-build` / §31 docs site
  builds end to end.

### Changed
- Lint (`ruff check`), format (`ruff format --check`), and type (`mypy src`)
  gates are now **green** on the full source tree (previously red baseline); mypy
  `ignore_missing_imports` is scoped to optional third-party extras only.
- Build report (`docs/reference/build-report-39.md`) status moved from PARTIAL to
  COMPLETE (offline/fake-provider scope); measured benchmark recorded (§24.3).

### Deprecated
- Nothing deprecated yet.

### Removed
- Nothing removed yet.

### Fixed
- (recorded as fixes land)

### Security
- (recorded as advisories land)

---

## [0.1.0] - 2026-08-07

The first public pre-release. This is a **technical preview**: the codebase
implements the complete v1 product surface, but the public label is a preview and
the API/storage surface is not yet compatible-stable (see [ROADMAP.md](ROADMAP.md)).

### Added

- **Core foundry pipeline** — turn permitted source documents into traceable,
  quality-gated SFT and preference datasets:
  - Safe intake with source documents treated as untrusted data; URL ingestion
    disabled by default and SSRF-protected when enabled.
  - Parsing and normalization, including a Docling adapter guarded by a resource
    guard (ADR `0003`) and golden-fallback parsers.
  - Structure-aware chunking as the default; optional DocETL gather profile guarded
    behind an explicit adapter (ADR `0004`).
  - Model gateway with provider routing, budgets, and a deterministic fake provider
    for offline/CI use; optional LiteLLM profile (ADR `0005`).
  - Generation topologies and a prompt library.
  - Validation/quality gating, privacy handling, license resolution (unknown source
    license ⇒ `review`, never auto-allowed for public release).
  - Split/version/export/publish with full source traceability.
- **Authoring formats** — SFT and preference (DPO-style) dataset construction with
  review workflows.
- **Interfaces**:
  - CLI (`uv run knovaryn ...`) with commands for demo, doctor, server, and pipeline
    operations.
  - MCP server exposing the authoring surface through typed tools (isolated from the
    underlying MCP framework, ADR `0002`).
  - REST API and a web console.
- **Storage** — local content-addressed store by default, optional S3-compatible
  backend, SQLite (WAL) default with PostgreSQL for production, behind a unified
  `ArtifactStore` (ADR `0006`).
- **Observability** — audit logging, telemetry, and cost accounting.
- **Deployment** — container and deployment assets under `deploy/`.

### Changed

- This is the first published release; there is no prior version to compare against.

### Fixed

- No prior fixes (first release); the repository is delivered with the full test
  suite passing against the offline/CI path.

### Security

- Secure-by-default posture implemented up front: remote handles are unguessable and
  ownership-bound; local HTTP binds to loopback with Host/Origin validation; no MCP
  tool accepts a shell command; provider keys are never accepted through tool
  arguments and are redacted. See [SECURITY.md](SECURITY.md) and `docs/security/`.

---

[0.1.0]: https://github.com/waalwalker1/knovaryn/releases/tag/v0.1.0
