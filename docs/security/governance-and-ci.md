---
description: >-
  Governance, CI, and supply-chain security: branch protection,
  pinned workflows, SBOM generation, dependency scanning,
  reproducible releases, and verify-release.
---

# Governance, CI & supply-chain security (WP L)

This page documents how Knovaryn is built, tested, released, and governed —
the CI / security / supply-chain / release layers (spec WP L). It is the
operational counterpart to the [hardening](hardening.md) and
[privacy & licensing](privacy-licensing.md) pages.

## Principles

- **Fail closed.** Any gate that cannot prove a property fails the build or the
  release. Export refuses on unresolvable lineage; a wheel containing
  secret-like content is never published.
- **No stored secrets for publishing.** Releases use **OIDC trusted
  publishing** to PyPI (`id-token: write`), so no `PYPI_API_TOKEN` is stored in
  the repo or Actions secrets.
- **Explicit, release-gated publishing.** Nothing pushes to PyPI / containers /
  datasets from a plain `main` commit. Publishing only happens on an explicit
  GitHub Release tag (`vX.Y.Z`), and only when the full package CI passed.
- **Private build process, public product.** Build tooling, prompts, and
  local build/audit artifacts are never committed into the public repo.

## CI layers

`.github/workflows/ci.yml` runs on every push/PR and is organized into isolated
jobs so a failure is attributed to one layer:

| Job | What it enforces |
|-----|------------------|
| `lint-type` | `ruff check` + `ruff format --check` on `src tests`, `mypy src` (per-module missing-import overrides only) |
| `test` | Full offline suite on Python 3.11 / 3.12 / 3.13 (all live/gated tiers excluded) |
| `test-tiers` | Each tier (`unit` / `integration` / `mcp` / `rest` / `chaos` / `release`) in an isolated job |
| `coverage` | `scripts/coverage_gate.py`: ≥75% overall branch on the core packages, ≥80% per critical module (documented exemptions only) |
| `platform-smoke` | Import + CLI + local-storage smoke on Windows and macOS |
| `docs` | `mkdocs build --strict` + markdown link check |
| `container` | Builds the image on `main` |

## Security scanning

`.github/workflows/security.yml` runs on every push/PR and weekly:

- **gitleaks** — leaked-secret detection (SARIF to code scanning).
- **pip-audit** — vulnerable-dependency audit (fails on known vulnerabilities).
- **bandit** (`-lll`) — static security scan of `src`.
- **Trivy** — container image, filesystem, and IaC/K8s manifest scans
  (CRITICAL/HIGH fail the job).
- **pip-licenses** — license inventory (drives license compliance).
- **SBOM** — anchore cycloneDX generated from `uv.lock`, uploaded as an
  artifact.

## Release / supply-chain pipeline

`.github/workflows/publish.yml` runs only on a GitHub **Release** event and
composes the WP L release safeguards:

1. **`package-ci`** — runs `scripts/package_ci.py`:
   build wheel + sdist, `twine check`, metadata verification, **wheel secret
   scan** (private keys / access keys / API tokens — any hit fails closed),
   clean-env install, and CLI / MCP / REST smoke from the installed wheel.
2. **`tag-version-consistency`** — the `vX.Y.Z` tag must equal `pyproject.toml`
   `project.version`.
3. **`ci-gate`** — the release SHA must have passing CI and security workflows.
4. **`deploy-e2e`** — the compose stack runs the image built from the exact
   published tag.
5. **`build`** — rebuilds and uploads the `dist/` artifact.
6. **`release-assets`** — attaches detached `SHA256SUMS`, a CycloneDX SBOM
   from the locked resolution, notes generated from `CHANGELOG.md`, and
   enforces that `0.x` tags are marked pre-release.
7. **`publish`** — uploads to PyPI via **OIDC trusted publishing** (`environment:
   pypi`, `id-token: write`). The `pypi` environment must be mapped to the
   `knovaryn` project in PyPI's trusted-publishers settings.
8. **`post-publish-verify`** — a clean environment resolves the just-published
   version from the public index.

![Knovaryn release supply chain — gates on the release SHA, artifact attachment, OIDC publish, post-publish verification, and local verify-release](../assets/release-supply-chain.png){: width="100%" }

Release artifacts are reproducible: `ReleaseBundle` uses fixed zip timestamps,
stable sorted file order, `JSON sort_keys`, and detached `.sha256` checksums,
and `knovaryn verify-release` independently verifies the detached checksum and
per-file manifest.

## Governance & dependency hygiene

- **Dependabot** (`.github/dependabot.yml`) opens weekly, capped PRs for Python
  deps (from `uv.lock`) and pinned GitHub Actions. Nothing auto-merges — every
  bump goes through normal review.
- **Protected branch** on `main`: require `lint-type`, `test`, `test-tiers`,
  `coverage`, `security`, and `platform-smoke` to pass before merge; require
  pull-request reviews; admin not allowed to bypass reviews.
- **CODEOWNERS** (`.github/CODEOWNERS`): security-sensitive areas
  (`infrastructure/intake/`, `infrastructure/auth/`, `SECURITY.md`) always pull
  in a security-aware reviewer.
- **Contributing / security** process: see `CONTRIBUTING.md` and `SECURITY.md`.
- **Vulnerability response**: HIGH/CRITICAL findings from any scan are release
  blockers; a coordinating fix lands through the same gated PR pipeline and is
  noted in the changelog.
