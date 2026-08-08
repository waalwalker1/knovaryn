# Knovaryn Roadmap

The Knovaryn codebase implements the **complete v1 product surface** today — the
full pipeline from permitted source documents to traceable, quality-gated SFT and
preference datasets is present, along with the CLI, MCP server, REST API, web
console, and exporter set. The roadmap below therefore maps **public maturity
labels** (technical preview → stable), not missing feature work. Each milestone
below is a statement of what the `0.x`/`1.0` release *signals* publicly, and what
hardening/verification work we complete before we affix that label.

> **Reading this roadmap.** "Implemented" refers to behavior present in the codebase.
> "Publicly labeled" refers to what a released version promises about stability,
> compatibility, and operational readiness. The gap between the two is exactly what
> each milestone closes.

Every milestone is gated by the release gate documented in
`docs/marketing/release-gate.md` and by the release process in
[GOVERNANCE.md](GOVERNANCE.md) §6.

---

## v0.1 — Technical preview

**Target: the first public alpha release.**

- [x] Core pipeline implemented: safe intake, parsing/normalization, structure-aware
      chunking, model gateway, generation topologies, validation/quality, privacy,
      licensing, split/version/export/publish.
- [x] Provenance as a first-class guarantee: every training example traced to its
      source document, version, and lineage.
- [x] Interfaces implemented: CLI, MCP server, REST API, web console.
- [x] Local distributed store and optional S3/SQLite/PostgreSQL backends implemented.
- [ ] **_Public label work remaining_**
  - [ ] Field/torture-test the offline demo and install paths across supported OSes.
  - [ ] Publish the first PyPI wheel and container images; verify reproducibility.
  - [ ] Complete end-user documentation and onboarding guides.
  - [ ] Confirm the CI release gate passes fully for a tagged alpha.

**Public commitment at v0.1:** *nothing about the API, storage schema, CLI flags, or
MCP tool surface is frozen.* Previews may churn without notice.

---

## v0.2 — Preference / review beta

**Target: signal that the SFT and preference (DPO-style) authoring loop is solid
enough for real review workflows.**

- [x] Preference dataset construction, quality gating, and review workflows implemented.
- [x] Human-in-the-loop review surfaces in the web console.
- [ ] **_Public label work remaining_**
  - [ ] Stabilize the preference record schema (prompt, chosen/rejected, trace metadata)
        behind an ADR before freezing it at v1.
  - [ ] Beta-test the review UX with external reviewers; incorporate feedback.
  - [ ] Harden audit/cost telemetry for longer-running review sessions.
  - [ ] Begin tracking a public API-compatibility policy in `CHANGELOG.md`.

**Public commitment at v0.2:** preference schemas and review-facing REST/MCP surfaces
are **approaching stable**; breaking changes are announced in `CHANGELOG.md` with
migration notes, not silent.

---

## v0.3 — Remote / team

**Target: signal real multi-user, remote operation is trustworthy.**

- [x] Remote/team capabilities implemented (ownership-bound handles, auth, audit, budget).
- [ ] **_Public label work remaining_**
  - [ ] Security review of the remote/auth surface (two-maintainer rule, see
        [GOVERNANCE.md](GOVERNANCE.md) §7).
  - [ ] Load/scale testing of the durable job engine in remote + concurrent-teams setups.
  - [ ] Publish deployment guides (`deploy/`) for the remote mode.
  - [ ] Hardening pass on SSRF, host validation, and secrets handling for remote use.

**Public commitment at v0.3:** remote/team deployment is documented, tested, and
security-reviewed; storage backend guarantees are pinned in the storage ADR.

---

## v0.4 — Advanced orchestration

**Target: richer programmatic and multi-stage authoring.**

- [x] Advanced orchestration primitives implemented (topologies, jobs, budgets,
      conditional gating, model routing).
- [ ] **_Public label work remaining_**
  - [ ] Document advanced orchestration patterns with worked examples.
  - [ ] Benchmarks for orchestration-heavy pipelines (`benchmarks/`).
  - [ ] Confirm the ML-extra surfaces (Docling, DocETL, LiteLLM, Hugging Face Hub)
        are fully verified and CI-covered where feasible.
  - [ ] Final dependency-baseline and supply-chain audit.

**Public commitment at v0.4:** orchestration APIs are feature-complete relative to the
v1 surface and covered by benchmarks; only stability/verification work remains before
freezing.

---

## v1.0 — Stable

**Target: the first stable, long-term-support release.**

- [ ] Public API freeze: CLI, REST, MCP tool surface, exporter formats, and storage
      schema are frozen and documented.
- [ ] Migration path and compatibility policy in place for the entire `0.x` line.
- [ ] Semver from here on: `1.x` releases only introduce breaking changes under a
      documented deprecation policy.
- [ ] Release gate fully green for a `1.0.0` tag: tests, coverage, docs, container,
      dependency, secret, and static-analysis scans.
- [ ] Governance, support, and contribution processes proven in operation.

**Public commitment at v1.0:** the documented surface is the contract. "Every
training example, traced to its source" is a guarantee users can rely on for
production use.

---

## Out of scope / non-goals (for now)

- A hosted/managed SaaS offering — Knovaryn is a self-hostable, open foundry.
- Guaranteed support SLAs — see [SUPPORT.md](SUPPORT.md).
- Adding training-data examples that embed source material without license
  resolution; provenance tracing is a hard invariant, not a roadmap feature.

## How this roadmap is maintained

The roadmap is owned by the maintainers and updated by PR. Substantive re-scoping
of a milestone is a decision and follows [GOVERNANCE.md](GOVERNANCE.md) §5; shipping
a version that changes the public label is a release-gate event (§6).
