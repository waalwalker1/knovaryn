# Knovaryn Governance

Knovaryn is an open-source project, and its governance is deliberately **lightweight**.
We favor clear, written decisions over process for its own sake. This document
describes the roles that keep the project healthy, how decisions get made, and the
rules we hold ourselves to — especially where security and trust are concerned.

The short version: contributions come from anyone; reviews and approvals come from
named maintainers; big or security-sensitive changes require multiple eyes and a
written decision record.

---

## 1. Principles

1. **Transparency by default.** Decisions that meaningfully shape the project are
   written down in public Architecture Decision Records (ADRs) under `docs/adr/`.
2. **Consent over consensus.** We aim for clear, documented consent, not unanimous
   agreement. Disagreement is resolved through the decision process in §5.
3. **Security is a two-person job.** Anything security-sensitive requires at least
   **two maintainers** to approve and must never move through the project silently.
4. **Anyone can contribute; maintainers serve the community.** Roles here are earned
   by sustained, trustworthy contribution, and they expire if participation lapses.
5. **Conflict of interest is disclosed, not hidden.** See §9.

## 2. Project roles

| Role | Responsibility | How you get it |
|---|---|---|
| **Contributor** | Opens issues, reviews, and submits PRs; reports bugs and parser regressions. | Anyone. No appointment needed. |
| **Reviewer** | Consistently reviews PRs, enforces quality/typing/testing standards, shepherds new contributions. | Appointed by maintainers from active contributors. |
| **Maintainer** | Approves and merges PRs; owns `docs/adr/` decisions; moderates issues; keeps repo healthy. | Appointed by existing maintainers after sustained high-quality, trusted participation. |
| **Security maintainer** | Triages and fixes vulnerabilities; owns the private reporting path; coordinates disclosure. | Appointed from maintainers; must follow the two-maintainer security rule. |
| **Release manager** | Cuts `CHANGELOG.md`-driven releases, tags, and publishes artifacts; coordinates the release gate. | Appointed by maintainers, rotating. |

The **Code of Conduct committee** is drawn from maintainers and handles
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) reports at `maintainers@knovaryn.dev`.

## 3. The maintainer model in practice

- **We keep it small and trusted.** Early on, the maintainer group is intentionally
  small (see [MAINTAINERS.md](MAINTAINERS.md)). As the community grows, trusted
  reviewers graduate to maintainer.
- **Lapsing.** A maintainer who is unresponsive for a prolonged period (roughly six
  months without any project interaction) may be marked **emeritus** by the rest of
  the group. This is not a demotion — it keeps the list honest, and returning is easy.
- **Removal** happens only for sustained Code of Conduct violations or a clear
  breach of trust, and only after an attempt to resolve it; it is always made
  public and recorded.

## 4. Issue and PR process (summary)

Full detail is in [CONTRIBUTING.md](CONTRIBUTING.md). Briefly:

- Bugs, features, parser regressions, and new-exporter requests use the issue templates.
- PRs are reviewed, must pass the CI gate (ruff, mypy, pytest with the non-live
  markers, docs build), and carry a signed DCO trailer.
- One maintainer approval merges ordinary PRs; **two** are required for
  security-sensitive or release-gate-affecting changes (§7).

## 5. Decision process (public ADRs)

Decisions that shape the project are captured as **Architecture Decision Records**
under `docs/adr/`, numbered sequentially, summarized in `DEcision_LOG.md` and
`SPEC_INDEX.md`. The current records are `0001`–`0006` (dependency baseline, MCP
and FastMCP isolation, Docling resource guard, DocETL profile, LiteLLM/model
gateway, storage backends).

### When an ADR is required

A new or updated ADR is required when a change:

- adds, removes, or swaps a **dependency** (see `0001-dependency-baseline`);
- changes the **domain model, provenance, or license handling**;
- changes a **public interface** (CLI, REST, MCP, web, exporter format);
- changes the **security posture** or safe defaults;
- changes storage, provider wiring, or the model gateway;
- resolves a previously open spec/upstream question.

### How a decision is made

1. **Propose.** Open a PR (or issue) that adds or edits an ADR in
   `docs/adr/NNNN-short-title.md` using the Status/Context/Decision/Consequences
   shape already used by the existing ADRs.
2. **Discuss.** The proposal is discussed in the PR. Maintainers and reviewers
   weigh in; contributors are welcome to comment.
3. **Approve.** Maintainers reach documented consent. For ordinary decisions one
   explicit approving maintainer plus the reviewing maintainer suffices.
   **Security-sensitive ADRs require two approving maintainers** (§7).
4. **Record.** The merged ADR is cross-linked in `DECISION_LOG.md` and the relevant
   `SPEC_INDEX.md` section. The status line in the ADR is updated to `Accepted`
   (or `Superseded`/`Rejected` with a pointer).

**Lazy consent / default behaviour.** If no maintainer objects within a reasonable
window (typically 5 business days for a routine ADR) and CI passes, the change may
be merged. Substantive objections halt the merge until addressed.

### Revisiting decisions

Any ADR can be superseded by a new ADR that references it. We prefer to amend with
a new record over editing history so the rationale stays legible.

## 6. Release process

Releases follow the roadmap maturity labels in [ROADMAP.md](ROADMAP.md) and the
release gate documented in `docs/marketing/release-gate.md`:

- A release is cut by the **release manager** from `main`,
  driven by `CHANGELOG.md` ([Keep a Changelog](https://keepachangelog.com/)).
- A release must pass the full CI gate, including dependency/container/secret and
  static-analysis scans, and must ship **no unaccepted critical/high vulnerability**.
- A release entry states what changed in terms of the **public labels** (see the
  roadmap note: the codebase may implement a far richer surface than its public
  maturity label advertises).

## 7. Security-sensitive changes: the two-maintainer rule

Security is the area where we are most conservative. Changes that touch any of the
following require **at least two approving maintainers**, one of whom should be a
**security maintainer** where practical:

- intake and URL/SSRF handling (`infrastructure/intake/`);
- authentication, authorization, secret handling, redaction (`infrastructure/auth/`);
- MCP/REST/web interfaces that handle untrusted input or invoke providers;
- parser/normalization code that processes **untrusted source documents**;
- the dependency baseline or supply-chain policy;
- the safe defaults (unknown license → `review`, URL ingestion off by default,
  no shell-command MCP tool);
- the disclosure of a vulnerability.

This rule also applies to **vulnerability fixes**: the fix, the advisory, and the
public disclosure are reviewed by at least two maintainers before anything ships.

## 8. Vulnerability reporting and disclosure

See [SECURITY.md](SECURITY.md) for the operational details. In summary:

- Vulnerabilities are reported **privately** (`security@knovaryn.dev`, or the GitHub
  private reporting path once enabled), never through public issues.
- The security maintainers acknowledge within **3 business days** and coordinate a
  fix before public disclosure.
- After a fix ships, disclosure is coordinated with the reporter, and credit is
  given unless anonymity is requested.

## 9. Conflict-of-interest policy

Maintainers and reviewers are expected to act in the project's interest and to be
candid about where their interests lie.

- **Disclose.** Anyone with a direct stake in a decision — for example, an employer,
  a funded employer-relationship, a competing product, or a personal financial
  interest in a dependency, provider, dataset, or vendor being chosen — must state
  that interest when the topic comes up. A brief, public note on the relevant PR,
  issue, or ADR is sufficient.
- **Recuse.** Where a conflict is material (e.g. approving a procurement/add of a
  product the person sells, or deciding a review outcome for their own employer's
  PR), the person should step back from **approving** that specific decision and let
  another maintainer carry it.
- **No bounty or quid pro quo.** Knovaryn contributions are not traded for favors —
  financially or otherwise. Do not use a maintainer role to steer the project toward
  a commercial interest (a vendor, a provider, a key, or a dataset) without open
  disclosure and consent.
- **Data licensing.** Because Knovaryn ingests source documents into training data,
  particular care is taken with any interested-party sourcing: contributions of data
  must be license-resolved and disclosed, consistent with §9 of CONTRIBUTING.md.
- **Review.** If a conflict is observed and not disclosed, any community member may
  raise it with the maintainers; the Code of Conduct committee can review it.

## 10. Changing this document

This governance document is itself a decision. Changes are proposed by PR or ADR,
reviewed by maintainers, and merged with at least two approving maintainers. It is
versioned implicitly by git history, and substantive changes get a changelog entry.

---

_Questions about governance? Contact `maintainers@knovaryn.dev` or open a
Discussion. We are friendly._
