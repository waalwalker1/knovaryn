# Changelog

All notable changes to Knovaryn are documented here, following the
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. This project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) starting at
v1.0.0; during the `0.x` public-maturity line compatibility is approached but not
yet guaranteed (see [ROADMAP.md](ROADMAP.md)).

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-08-22

### Fixed
- **MCP SDK support contract**: declared range is now `mcp>=1.28,<3` and an
  official acceptance matrix runs the full MCP lifecycle against both `1.x`
  and `2.x` pins (stdio + authenticated streamable HTTP + bind-refusal),
  wired into CI as a required job.
- **Async shutdown hygiene**: SQLite/aiosqlite connections now use `NullPool`
  and engine disposal is shielded, eliminating post-loop
  `RuntimeError('Event loop is closed')` worker-thread noise when lifespans
  tear down inside a cancelled anyio scope; regression tests plus a
  warnings-as-errors policy (`PytestUnhandledThreadExceptionWarning`,
  `PytestUnraisableExceptionWarning`, incomplete pydantic field definitions).
- **Provenance location precision**: every source span carries a
  machine-verifiable `precision` derived from stored parser evidence
  (`exact_bbox` / `exact_page` / `page_range` / `section` / `chunk` /
  `unknown`) via `SourceSpan.with_derived_precision`; Docling page/bbox
  provenance flows through chunker to spans to lineage (REST + MCP) and
  export manifests; markdown/text sources honestly report lower precision
  instead of fabricating page numbers.
- **Schema evolution**: `create_all` now performs idempotent additive column
  migration so databases created by older versions upgrade in place; a new
  Alembic revision (`b81d4f6a2c39`) matches the ORM metadata exactly.
- **Version synchronization**: single authoritative `__version__` feeds
  CITATION.cff, codemeta.json, MkDocs config, container labels, REST/MCP
  servers and the README marker (`scripts/check_version_sync.py --check`).

### Added
- **Semantic validation profiles** (`quality.semantic_profile`): explicit
  `offline-fast` (deterministic-only, network-free) and `certified-semantic`
  (deterministic first, cited-evidence-only judge second via fingerprinted,
  cached, budget-accounted `ModelGateway.judge`). Deterministic
  contradictions can never be overridden; unavailable judges yield
  `unverified`, never `verified`. Adversarial benchmark with false-accept /
  false-reject rates and Wilson confidence intervals.
- **Certified pairwise preference profile** (`preference.profile`):
  two-order evidence-cited judge with randomized presentation, minimum
  preference margin, length/style signature detection, classified
  rejected-defect requirement, and fail-closed lineage recording.
- CLI reference generated from the real Typer command tree
  (`scripts/generate_cli_reference.py`) with CI drift checks and a command
  tree snapshot test.

### Changed
- REST API reports the real application version (`__version__`) instead of a
  stale literal; MCP health tool exposes `server_version`.
- CITATION.cff no longer carries a placeholder DOI pending real registration.

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
