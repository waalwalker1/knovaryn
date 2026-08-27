# Knovaryn Roadmap

Knovaryn is an open-source, self-hosted, MCP-native training-data foundry: turn
permitted documents into traceable, quality-gated SFT and preference datasets.
The codebase implements the **complete v1 product surface** — the full pipeline
from permitted source documents to traceable datasets is present, along with the
CLI, MCP server, REST API, web console, and exporter set. The roadmap therefore
maps **public maturity labels** (alpha → stable), not missing feature work. Each
milestone below states what the `0.x`/`1.0` release *signals* publicly, and what
hardening/verification work we complete before we affix that label.

> **Reading this roadmap.** "Implemented" refers to behavior present in the codebase.
> "Publicly labeled" refers to what a released version promises about stability,
> compatibility, and operational readiness. The gap between the two is exactly what
> each milestone closes. A capability whose tests pass on synthetic fixtures is not
> yet *stable*: stability includes compatibility commitment and operational proof.

Every release is gated by the release process in [GOVERNANCE.md](GOVERNANCE.md) §6
and the CI / supply-chain pipeline documented in
[docs/security/governance-and-ci.md](docs/security/governance-and-ci.md).

---

## Shipped

### v0.1.0 — Technical preview (2026-08-07)

- [x] Core pipeline implemented: safe intake, parsing/normalization, structure-aware
      chunking, model gateway, generation topologies, validation/quality, privacy,
      licensing, split/version/export/publish.
- [x] Provenance as a first-class guarantee: every training example traced to its
      source document, version, and lineage.
- [x] Interfaces implemented: CLI, MCP server, REST API, web console.
- [x] Local content-addressed store and optional S3/SQLite/PostgreSQL backends implemented.
- [x] Secure-by-default posture: untrusted-document handling, SSRF-protected (opt-in)
      URL ingestion, loopback-only local HTTP, no shell-command MCP tools.

**Public commitment:** *nothing about the API, storage schema, CLI flags, or MCP
tool surface was frozen.* Preview releases could churn without notice.

### v0.2.0 — Foundry product surface and supply chain (2026-08-21)

- [x] **First PyPI publication** (`pip install knovaryn`) via OIDC trusted publishing.
- [x] Durable job engine (lease-based claims, heartbeats, crash recovery) and worker
      topology, chaos-tested.
- [x] Typed REST API with status-code contracts, scopes/tenancy, safe binding, an
      accessible web console, and per-principal rate limiting.
- [x] Production deployment assets: Compose topology, Kubernetes kustomize base
      (migration Job, network policies, PDBs), backup/restore runbook.
- [x] Supply chain: tiered CI matrix, coverage gate, security scanning, SBOM,
      **release checksums**, detached-checksum reproducible releases
      (`verify-release`), Sigstore provenance on PyPI.
- [x] 8-format export with artifact-first intake and golden-corpus regression tests.
- [x] End-user documentation: full MkDocs material site (quickstart, references,
      security, operations) published to GitHub Pages.

### v0.2.1 — Compatibility, provenance, semantic validation, and release integrity (2026-08-25)

- [x] **MCP dual-major compatibility**: declared range `mcp>=1.28,<3`, official
      acceptance matrix running the full MCP lifecycle against both `1.x` and `2.x`
      pins (stdio + authenticated streamable HTTP + bind-refusal), required in CI.
- [x] **Provenance precision**: every source span carries machine-verifiable
      `precision` derived from stored parser evidence; Docling page/bbox provenance
      flows through chunker → spans → lineage → exports; markdown/text sources
      report lower precision honestly instead of fabricating page numbers.
- [x] **Semantic validation profiles**: explicit `offline-fast` (deterministic-only)
      and `certified-semantic` (deterministic first, cited-evidence judge second,
      budget-accounted, fail-closed) quality profiles, with adversarial benchmark
      evidence and Wilson intervals.
- [x] **Certified pairwise preference profile**: two-order evidence-cited judging
      with randomized presentation, minimum margin, style-signature detection, and
      classified rejected-defect requirements.
- [x] **Async shutdown hygiene**: `NullPool` SQLite connections and shielded engine
      disposal eliminate post-loop errors during lifespan teardown; enforced by a
      warnings-as-errors test policy.
- [x] **Schema evolution**: idempotent additive-column migration for databases
      created by older versions, plus a matching Alembic revision.
- [x] **Release integrity**: single authoritative version feeding every public
      surface (`scripts/check_version_sync.py`), package clean-install verification
      in the publish flow, and **exact-SHA deployment E2E** proving the released
      image builds and runs from the tagged commit.

---

## Current line: `0.x` — alpha

During the `0.x` public-maturity line Knovaryn is **alpha**: compatibility is
approached but not guaranteed, and breaking changes are announced in
[CHANGELOG.md](CHANGELOG.md) with migration notes rather than made silently.
Unreleased work accumulates under the changelog's `[Unreleased]` heading.

---

## Future milestones

### v0.3 — Remote/team trust

**Target: signal that real multi-user, remote operation has been externally
validated.**

- [ ] External security review of the remote/auth surface (intake, authz,
      secrets handling) — the internal two-maintainer rule
      ([GOVERNANCE.md](GOVERNANCE.md) §7) stays in force meanwhile.
- [ ] Larger-scale multi-user load testing of the durable job engine under
      concurrent teams and realistic failure injection.
- [ ] Reviewer UX feedback round with external reviewers on the web-console
      review surfaces, incorporating findings into the console and REST flows.
- [ ] Published container images, if and when the owner chooses a registry
      distribution channel (decision record required before publishing).

**Public commitment at v0.3:** remote/team deployment externally reviewed,
load-tested, and honestly benchmarked.

### v0.4 — Evidence maturity

**Target: replace synthetic-fixture evidence with real-world evidence.**

- [ ] Live-provider benchmark evidence alongside today's deterministic offline
      benchmarks (methodology already defined in
      [docs/reference/benchmark-methodology.md](docs/reference/benchmark-methodology.md)).
- [ ] Independent downstream evaluation: train small models on Knovaryn-exported
      datasets through third-party harnesses and publish the results verbatim.
- [ ] Advanced orchestration patterns documented with worked examples.
- [ ] Final dependency-baseline refresh and supply-chain audit for the freeze.

**Public commitment at v0.4:** every quality and benchmark claim is backed by
evidence a third party can reproduce end-to-end.

### v1.0 — Stable

**Target: the first stable, long-term-support release.**

- [ ] **Public API compatibility policy** in force: CLI, REST, MCP tool surface,
      exporter formats, storage schema frozen, documented, and covered by a
      deprecation policy with migration notes.
- [ ] Migration path and compatibility policy covering the entire `0.x` line.
- [ ] Semver from here on: `1.x` releases introduce breaking changes only under
      the documented deprecation policy.
- [ ] Governance, support, and contribution processes proven in operation over a
      sustained period, not merely written down.
- [ ] Release gate fully green for a `1.0.0` tag, including the external reviews
      above.

**Public commitment at v1.0:** the documented surface is the contract. "Every
training example, traced to its source" is a guarantee users can rely on for
production use.

---

## Out of scope / non-goals (for now)

- A hosted/managed SaaS offering — Knovaryn is self-hosted software plus a Python
  library; the GitHub Pages site is documentation, not a service endpoint.
- Guaranteed support SLAs — see [SUPPORT.md](SUPPORT.md).
- Adding training-data examples that embed source material without license
  resolution; provenance tracing is a hard invariant, not a roadmap feature.

## How this roadmap is maintained

The roadmap is owned by the maintainers and updated by PR. Substantive re-scoping
of a milestone is a decision and follows [GOVERNANCE.md](GOVERNANCE.md) §5; shipping
a version that changes the public label is a release-gate event (§6).
