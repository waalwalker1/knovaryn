# Knovaryn — Product & Positioning

**Status:** Companion to `one-pager.md` (the pitch) and `peer-comparison.md`
(the capability table). This page answers the strategic question: *what did we
build, why is it useful, where does it stand, and what's the honest next move.*

---

## 1. What we built — in one paragraph

Knovaryn is an **open-source, MCP-native training-data foundry**. It turns the
documents you're *permitted* to use (PDF, PPTX, HTML, Word) into **traceable,
quality-gated SFT and preference datasets** that any MCP-capable agent
(Claude Code, Cursor, etc.) can build on your behalf. The whole pipeline —
intake → parse → split → plan → generate → validate → version → export →
publish — runs on a **durable job engine** behind **four interfaces on one
core**: CLI, the `knovaryn_mcp` MCP server, a REST + web console, and a Python
SDK.

It is real engineering, not a demo shell: ~10.7k lines of Python in `src/`,
**233 passing test functions** (branch coverage ≥ 70%, CI-enforced), a **deterministic
offline provider** (no keys, no network), **enforced provenance**, and a
**quarantining quality gate**.

## 2. Why it's useful — the value, honestly framed

**The core promise:** *Every training example, traced to its source.*

| Pain | Knovaryn's answer | Who feels it |
|---|---|---|
| "I can't prove where this example came from." | Span-level evidence (`source_span_ids`, `content_hash`), enforced, exportable into the dataset card. | Applied-LLM teams, auditors, clients |
| "A crashed job made me pay twice." | Durable, idempotent, checkpointed jobs; resume without re-spending tokens. | Anyone doing long billable runs |
| "We generated N rows — no idea if they're any good." | Multi-dimension scoring with reason codes; weak rows **quarantined**, never exported. | Anyone fine-tuning at work |
| "I'm locked to one vendor/trainer." | Provider-agnostic `ModelGateway` + trainer-native exporters (TRL, LLaMA-Factory, JSONL, Parquet). | Portability-conscious teams |
| "Do I even have the rights?" | License registry + privacy gate; publication **dry-run by default**. | Regulated/legal-sensitive domains |

**Product, library, or service?** All three, from one codebase:

- **Product** — installable CLI, local web console, REST control plane, polished MCP suite. Works fully offline.
- **Library/SDK** — the same services importable in Python for your own agents and pipelines.
- **Service** — over MCP/REST it behaves like a managed capability your agents call on demand: *"ingest this, build SFT + preference data, gate it, hand me a trainer-ready bundle."*

## 3. How we're doing vs. peers

The honest capability table with 8 peers (Docling MCP, DocETL, Distilabel,
Synthetic Data Kit, Augmentoolkit, Easy Dataset, Bespoke Curator,
AI-Dataset-Generator) lives in `peer-comparison.md`. The strategic summary:

**Where Knovaryn genuinely differs (real differentiators):**
1. **MCP is the interface, not a wrapper.** The closest MCP-native peer (Docling MCP) is parse-only; Knovaryn is the document→dataset loop *as* an MCP agent experience.
2. **Evidence is enforced, not decorative.** Span-level provenance that survives into exports.
3. **Durable resume is a money story.** Checkpointed, idempotent jobs avoid duplicate token spend.
4. **Quality gate with quarantining reasons**; license + privacy gate before public export.
5. **Local-first → team-ready in one codebase.** Key-free offline demo through governed PostgreSQL+S3 teams.

**Where we're honest about the peers leading:**
- Docling/Docling MCP: better general parsing/OCR — and we depend on Docling for parsing.
- DocETL: more flexible declarative extraction over big collections.
- Distilabel: more mature LLM-as-judge ecosystem + Argilla review UI.
- Synthetic Data Kit / Distilabel: far larger communities and adapters today.

**Bottom line:** the *differentiation is real and defensible*, but the *standing
is incipient*. At 0.1.0 alpha with no external users yet, we are a well-
engineered candidate in an open gap — not yet a proven ecosystem leader. The
gap in the market is ours to claim, but only external verification will convert
that into credibility.

## 4. Product & service status today

- **Maturity:** 0.1.0 — **technical preview / alpha.** API and storage are *not* yet frozen.
- **Engineered to:** lint/type gates green; offline test suite green; docs site builds; Alembic migration baseline; secret-audited (no keys committed); `SECURITY.md`, governance, and legal processes in place.
- **Not yet proven externally:** no real users, no published reproducible benchmark numbers (methodology exists), no public wheels/containers, no 1.0 release-gate pass.

## 5. Honest next move — should we publish PyPI wheels?

**Short answer: yes — publish an editable alpha wheel now, and treat it as the
community-verification experiment, not as a "stable" release.**

**Why it's the right move to win the traceability story:**
- "Every example traced to its source" is a *claim people can only judge by
  running it*. A wheel makes that a one-line install (`pip install knovaryn`)
  instead of a clone+build. No users means the only way to get verifiers is to
  lower the friction to zero.
- Your own `ROADMAP.md` already lists "publish the first PyPI wheel and
  container images" as a **v0.1 public-label work item** — it's not gated by the
  heavier 1.0 release gate, which is reserved for declaring *stable*.
- The packaging is **already production-ready in the repo**: a proper hatchling
  `pyproject.toml` with name/version/readme/classifiers, a `knovaryn` CLI entry
  point, typed optional extras, and `build` + `twine` already in the `dev` extra.

**The honest caveats, so we don't overclaim:**
- An **alpha wheel must be labeled 0.1.0-alpha or 0.1.0 with "alpha" in the
  classifiers** and a loud "technical preview — not stable" note in the README.
  Do **not** call it stable or production-ready; that is what the `release-gate.md`
  nine items guard.
- **You must supply the PyPI token** (from pypi.org) — I can prepare everything
  and the commands, but only you can create the account/token and the secret in
  CI.
- **Name clearance:** confirm `knovaryn` is free on PyPI before publishing (it
  is distinct from the legacy `OmniTrain`/`omnitrain` names — the package name
  is already clean, which satisfies release-gate item 1's core intent).
- Keep the **lean core** (no heavy extras) as the base install exactly as
  configured, so `pip install knovaryn` works offline without docling/litellm.

**What I can do now (and what I'd recommend we do next):**

1. **Add a PyPI publish workflow** (`.github/workflows/publish.yml`) that builds
   the wheel/sdist with `build`, uploads to TestPyPI on tags, and to PyPI via a
   `PYPI_TOKEN` secret — I can write this and either keep it ready or wire it up.
2. **Polish alpha release metadata** — tweak the deprecated `license` field to
   the modern SPDX string and confirm the README badge/links render on PyPI.
3. Optionally set up **GitHub Releases + auto-draft** so each tag surfaces a
   changelog + wheel link.

The single biggest unlock for the "traceability story" is **making it a
one-command install** and letting a few early developers run the offline demo
and inspect the dataset card. That converts an internal claim into external
verification — exactly what a 0.x alpha is for.

---

> **Guardrail:** none of the above means Knovaryn is "stable" or "production
> ready." Alpha = invite early developers to *verify*, learn from them, and
> harden toward the 1.0 release gate. See `release-gate.md` (1.0), `ROADMAP.md`,
> and `SECURITY.md`.
