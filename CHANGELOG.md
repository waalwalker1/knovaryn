# Changelog

All notable changes to Knovaryn are documented in this file.

During the `0.x` public-maturity line Knovaryn is an **alpha**: compatibility
is approached but not guaranteed, and breaking changes are announced here with
migration notes (see [ROADMAP.md](ROADMAP.md) for the maturity milestones).
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Original brand identity: Tracemark logo family, design tokens, and a
  documented design system (`docs/assets/brand/`, `docs/design-system/`).
- Canonical benchmark methodology (`docs/reference/benchmark-methodology.md`)
  and a current benchmark report with three-run reproducibility evidence
  (`benchmarks/report-0-2-1.md`).
- ADR-0007: dual-major MCP SDK compatibility decision record, superseding
  ADR-0002's adapter guidance with the tested 1.x/2.x acceptance matrix.
- Visual-asset governance: `scripts/check_visual_assets.py` and the
  reproducible brand/diagram/screenshot generators under `scripts/visuals/`.
- Browser and accessibility verification for the documentation site
  (`tests/browser/`).

### Fixed
- **Release-bundle reproducibility**: release bundles no longer inherit
  wall-clock UUIDv7 handles — `IdGenerator(seed=...)` provides opt-in
  deterministic identifiers for reproducible-mode runs, so identical inputs
  produce byte-identical bundles (`H(R1)=H(R2)=H(R3)`, enforced by
  `benchmarks/run_report.py` and regression tests). Production identifiers
  remain unguessable UUIDv7s, and security tokens stay `secrets`-based in
  every mode.

### Changed
- Security and maintainer contact routes: vulnerability reporting now goes
  exclusively through GitHub private vulnerability reporting (no
  project-domain email exists); maintainer/CoC/legal contact updated.
- Redesigned README and documentation site presentation (original visual
  identity, interactive pipeline and architecture explorers with static
  fallbacks); regenerated all architecture diagrams for readability.
- Release-date hygiene: v0.2.1's publication date corrected to 2026-08-25
  across CITATION.cff, codemeta.json, and this changelog; version-sync
  checks extended to cover release dates, project URLs, and social-preview
  wiring.

## [0.2.1] - 2026-08-25

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

## [0.2.0] - 2026-08-21

### Added
- **Durable jobs & workers**: lease-based job engine with atomic claim,
  heartbeats, checkpointing, crash recovery, and budget accounting.
- **MCP product surface**: typed tool suite over stdio and streamable HTTP,
  isolated behind the MCP adapter boundary.
- **REST API + web console**: typed API with status-code contracts,
  scopes/tenancy, safe binding, an accessible console, and per-principal
  rate limiting.
- **Deployment**: production Compose topology (api/worker/postgres/minio/
  proxy), Kubernetes kustomize base (migration Job, network policies, PDBs),
  metrics endpoints, and a backup/restore runbook.
- **Supply chain**: CI matrix with tiered jobs, coverage gate, security
  scanning, SBOM, OIDC publishing, and reproducible releases with detached
  checksums (`verify-release`).
- **8-format export** with an artifact-first intake service and golden-corpus
  regression tests.

### Fixed
- **Truth-before-reach remediation**: every quality gate in the acceptance
  path is wired into the product, not only tested as library code — semantic
  consistency (causal reversal, number/unit mismatch, negation flip,
  entity-role reversal) is a critical rejection dimension applied to every
  example.

## [0.1.1] - 2026-08-13

### Fixed
- Production-correctness pass across provenance, quality, MCP, REST,
  deployment, documentation, and release preparation.

## [0.1.0] - 2026-08-07

The first public pre-release. This is a **technical preview**: the codebase
implements the complete v1 product surface, but the public label is a preview
and the API/storage surface is not yet compatible-stable (see
[ROADMAP.md](ROADMAP.md)).

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

### Security

- Secure-by-default posture implemented up front: remote handles are unguessable and
  ownership-bound; local HTTP binds to loopback with Host/Origin validation; no MCP
  tool accepts a shell command; provider keys are never accepted through tool
  arguments and are redacted. See [SECURITY.md](SECURITY.md) and `docs/security/`.

[Unreleased]: https://github.com/waalwalker1/knovaryn/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/waalwalker1/knovaryn/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/waalwalker1/knovaryn/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/waalwalker1/knovaryn/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/waalwalker1/knovaryn/releases/tag/v0.1.0
