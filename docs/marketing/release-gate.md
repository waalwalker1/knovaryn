# Knovaryn — Public 1.0 Release Gate

**Document status:** DRAFT — the authoritative checklist the project must pass to label a release **1.0 / stable** (do not use the word "stable" or "production-ready" until every item is satisfied and evidence is linked). Mapped from the master spec §4.5 (success measures / release gates) and §40 (owner acceptance checklist).

**Usage:** Every item must be **checked with evidence** (a link, a test name, a report, or counsel sign-off) — not merely asserted. Anything unverifiable stays un-checked and blocks the 1.0 label.

---

## 1. Name clearance
- [ ] GitHub, PyPI, and chosen domain names confirmed available/owned; no confusingly similar prior occupant.
- [ ] Trademark + phonetic-similarity clearance documented (see `launch-checklist.md` §A.1), with dates.
- [ ] No legacy-brand identifiers in any public product surface (the identity and branding tests pass).

## 2. Stable APIs
- [ ] Public CLI flags, MCP tool names/inputs/outputs, and configuration schema are frozen; deprecation policy documented.
- [ ] Canonical data model and export formats (canonical JSONL, Parquet, TRL conversational, LLaMA-Factory ShareGPT) are versioned and documented; no silent format drift.
- [ ] Configuration precedence and admin-protected keys documented and tested.

## 3. MCP compatibility tests
- [ ] MCP server (`knovaryn_mcp`) passes the relevant MCP conformance/initialization handshake tests.
- [ ] Interop verified against at least two independent MCP clients, including at least one named agent (e.g., Claude Desktop) for high-level tool calls.
- [ ] Idempotent tool calls (create/run/export) behave correctly on retry.

## 4. External reproduction
- [ ] A third party (outside the maintainers) can install `knovaryn`, run the offline demo, produce an export, and confirm the release-gate artifacts, following only the public docs.
- [ ] Reproduction recorded (issue/PR or attestation) for the 1.0 commit.

## 5. Benchmark + limitations report
- [ ] A reproducible benchmark report exists per `benchmark-methodology.md` (≥3 reps, pinned versions, cost model dated) for the public corpus, covering fixed-character vs structure-aware vs DocETL gather.
- [ ] A published **limitations** document states clearly what is and is not measured/claimed (no bias-free, no hallucination-free, no model-improvement guarantee; license handling is not legal clearance).
- [ ] Benchmark data and configs committed to `benchmarks/` for reuse.

## 6. Security policy + disclosure
- [ ] `SECURITY.md` present with a coordinated-disclosure process and a contact.
- [ ] `pip-audit` clean at release commit; dependency baseline documented (ADR-0001).
- [ ] Security architecture documented (`docs/security/`): auth scopes, secrets, PII quarantine, admin-protected config.

## 7. Signed artifacts + SBOMs
- [ ] Release artifacts (wheels/sdist and source tags) signed; signature verification instructions in docs.
- [ ] SBOM generated for the released build (dependencies with hashes and licenses) and published with the release.

## 8. Dataset-card / license review
- [ ] Dataset-card generation produces complete cards (train/val/test counts, source manifest, license report, privacy report, quality report).
- [ ] Licensing review done for any released/sample dataset: every source's redistribution rights verified permitted; blocked/unknown sources excluded from public export.
- [ ] Privacy review done: no high-confidence PII in exported/public content.

## 9. No unaccepted critical/high vulnerability
- [ ] All known critical- and high-severity vulnerabilities in the released dependency set and product code are fixed; any remaining is explicitly accepted in writing with a documented rationale and tracking issue.
- [ ] No reported security issue older than the disclosure SLA remains unaddressed.

---

## Release-gate decision

| Item | Status | Evidence link |
|---|---|---|
| 1 Name clearance | ☐ | |
| 2 Stable APIs | ☐ | |
| 3 MCP compat tests | ☐ | |
| 4 External reproduction | ☐ | |
| 5 Benchmark + limitations report | ☐ | |
| 6 Security policy + disclosure | ☐ | |
| 7 Signed artifacts + SBOMs | ☐ | |
| 8 Dataset-card / license review | ☐ | |
| 9 No unaccepted crit/high vuln | ☐ | |

**Gate rule:** All nine items **Pass** (evidence-linked) → the release may be labeled 1.0. Otherwise it remains 0.x and must not be called stable. Re-run this gate for every future major/minor release; patch releases re-check items 3, 5, 6, 7, 9 at minimum.
