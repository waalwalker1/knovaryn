# Knovaryn — One-Pager

**Category:** Open-source, MCP-native training-data engineering
**Pitch:** Turn permitted documents into traceable, quality-gated SFT and preference datasets that any MCP-capable agent can build, review, and export.
**Tagline:** *From documents to defensible training data.*
**License:** Apache-2.0 · **Python** ≥ 3.11 · **Status:** 0.1.0 (alpha), public 1.0 gate defined in `release-gate.md`.

---

## What Knovaryn is

Knovaryn is an open-source **training-data foundry** for small language-model teams that need to go from a stack of permitted documents to a defensible supervised fine-tuning (SFT) or preference (DPO/KTO) dataset — without hand-waving about *where the examples came from* or *whether they're any good*.

It is **MCP-native**: the whole pipeline — intake, planning, estimation, generation, validation, review, export, publication — is exposed as Model Context Protocol tools that any MCP-capable agent (Claude Code, or any MCP client) can drive. You use natural language to build a dataset; Knovaryn turns it into a traceable, reproducible job.

## The problem

Building a training dataset by hand is slow, expensive, and — more importantly — indefensible. Common failure modes:

- **No evidence.** Examples are generated "from memory" with no link back to the source document, so you can't verify grounding, quote page or section, or defend the data to reviewers, clients, or auditors.
- **No quality signal.** "We generated N examples" says nothing. Every row is the same weight even when many are wrong, ungrounded, or trivially separable junk.
- **Duplicated spend and lost work.** A long generation job dies on a flaky connection and the operator restarts it, paying twice for the same tokens.
- **Walled-in output.** A great dataset stuck in a proprietary JSON dump that only one trainer can read.
- **Licensing guesswork.** No record of whether a source document was actually redistributable before its content enters a public dataset.

## What makes Knovaryn different

Five messaging pillars — each one a concrete mechanism, not a slogan:

1. **Trace every example.** Every accepted `TrainingExample` carries evidence references (`source_document_ids`, `source_span_ids`), a `content_hash`, generation candidate IDs, and a lineage back to the parsed document and chunk. Exports can include the evidence so a dataset card can say *where* each example came from, down to page and section.
2. **Resume expensive work.** Jobs run on leased workers with heartbeats, output checkpoints, and idempotency keys. If a worker dies or the connection drops, the job resumes from its last checkpoint — finished chunks are never re-generated, so you don't pay twice.
3. **Bring your own model and trainer.** Knovaryn does not lock you in. Provider adapters (OpenAI-compatible, Anthropic-compatible, DeepSeek via OpenAI-compatible base URL) sit behind a `ModelGateway`; a deterministic **fake provider** powers the offline demo with no credentials. Exporters emit TRL conversational, LLaMA-Factory (ShareGPT), canonical JSONL, and Parquet. Bring your own generator, critic, and verifier; take your dataset to your own trainer.
4. **Run local or governed.** The default `offline-demo` profile runs fully local with no network and no keys. For teams, profiles (`fast-local`, `balanced`, `high-quality`, `air-gapped`, `enterprise`) plus OAuth-style resource scopes and admin-enforced policy give you governed, auditable runs.
5. **Measure quality, not merely generate.** Every candidate is scored across dimensions (grounding, instruction fulfillment, preference signal, artifact resistance) against a dated policy. Acceptance produces *reason codes*; weak examples are **quarantined with a reason** rather than silently included. Versioned dataset cards and benchmark reports accompany releases.

## Who it's for

- **Small applied-LLM teams** turning internal, permitted documentation into SFT fine-tune data — and needing to show their work.
- **Domain practitioners** (finance, law, compliance, support, healthcare-adjacent) who can't ship public datasets without provenance and licensing discipline.
- **MCP developers and power users** who want to drive a data-engineering pipeline from natural language inside their agent.
- **Consultants and agencies** producing custom datasets for clients who will ask "where did this example come from, and why is it in here?"
- **Researchers** publishing reproducible, redistributable public datasets from public-domain sources.

It is **not** (yet) for training frontier-scale models, nor for processing documents you don't have permission to use. It gates licensing, but it is not a substitute for your own legal review (see `release-gate.md`).

## Quickstart

Requires Python ≥ 3.11. Recommended: a virtualenv.

```bash
# Install the lean core (no heavy extras needed for the offline demo)
pip install -e ".[dev]"

# Initialize state dir and run the MCP server against the offline-demo profile
knovaryn init                        # creates .knovaryn/ state
knovaryn mcp --profile offline-demo  # starts MCP server (credential-free)
```

Or run the same pipeline through the CLI:

```bash
knovaryn project create --name "My First Dataset"
knovaryn source add ./docs/example.pdf --declared-license "CC-BY-4.0"
knovaryn plan estimate --target 500      # dry-run cost & yield estimate
knovaryn run --profile balanced
knovaryn review list --status review
knovaryn export --format trl-conversational --format llamafactory-sharegpt
```

From any MCP client, these become tools the agent calls on your behalf. For the full walkthrough, see `demo-script.md`.

> **Honest limitations:** Knovaryn measures quality against its configured policy and heuristics; it does **not** guarantee the absence of bias or hallucination, and it does **not** guarantee that a generated dataset improves any model. It gates licensing based on declared and detected signals but is **not** legal clearance. Read `release-gate.md` and `benchmark-methodology.md` before relying on outputs for anything regulated.
