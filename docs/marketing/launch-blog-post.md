# Announcing Knovaryn: an open, MCP-native training-data foundry

*Draft launch blog post · Knovaryn 0.1.0 · 2026-08-07*

> Caveat at the top (edited into final): *This is a technical announcement of a 0.1.0 alpha. We are not claiming legal clearance, dataset perfection, or guaranteed model improvement. Knovaryn is a tool for making training-data pipelines traceable and quality-gated — see the honest-limitations note at the bottom and the release gate before relying on it for anything regulated.*

Small teams building fine-tuned models have a growing data problem. The model APIs got cheap and good, and the trainers (TRL, LLaMA-Factory, Axolotl, ...) got easy. What stayed manual is the actual **data**: going from a stack of documents you're allowed to use to a supervised fine-tuning (SFT) or preference (DPO/KTO) dataset that a reviewer can trust.

Most pipelines that do this today share a few weaknesses. They generate rows without linking each one back to the source, so "grounding" is an assumption, not a pointer. They treat every generated row as equal even when a chunk of them are ungrounded or trivially wrong. When a long job dies on a flaky connection, the operator restarts it and pays for the same tokens twice. And whatever dataset they produce tends to be locked to one trainer's format.

Today we're releasing **Knovaryn** as an open-source, **MCP-native training-data foundry** — Apache-2.0, Python ≥ 3.11, at 0.1.0.

## The one-paragraph pitch

Turn permitted documents into traceable, quality-gated SFT and preference datasets that any MCP-capable agent can build, review, and export. Tagline: *from documents to defensible training data.*

## What you actually get, in five mechanisms

**1. Every example is traced to its source.** A generated `TrainingExample` isn't just text. It carries `source_document_ids`, `source_span_ids`, a `content_hash`, and generation-candidate IDs. From any example you can walk the lineage: example → candidate → chunk → parsed document (via Docling) → source PDF page. Evidence is a pointer you can open, not a promise.

**2. Expensive work resumes, not restarts.** Jobs are durable and idempotent, run on leased workers with heartbeats and checkpoints. If a worker dies or you lose the connection, the job resumes from its last checkpoint. Finished chunks are never regenerated — for billable generation this is the difference between a job that survives bad Wi-Fi and one that silently double-bills.

**3. Bring your own model and trainer.** Knovaryn doesn't own your stack. Provider adapters (OpenAI-compatible, Anthropic-compatible, DeepSeek via an OpenAI-compatible base URL) sit behind a `ModelGateway` port, with configurable generator, critic, verifier, and embedding. There's even a deterministic **fake provider** so the whole pipeline runs offline with no credentials. On the way out, exporters produce TRL conversational, LLaMA-Factory ShareGPT, canonical JSONL, and Parquet. You bring the model, you bring the trainer, Knovaryn only mediates the data.

**4. Run local or governed.** The default `offline-demo` profile is fully offline. Further profiles (`fast-local`, `balanced`, `high-quality`, `air-gapped`, `enterprise`) plus OAuth-style resource scopes (`projects:read`, `runs:execute`, `datasets:publish`, ...) and admin-enforced policy make it usable in a governed environment without losing the local story.

**5. Measure quality, don't just generate.** Every candidate is scored across dimensions — grounding, instruction fulfillment, preference signal, artifact resistance — against a dated acceptance policy. Acceptance records *reason codes*. Weak examples are **quarantined with a reason** (e.g., `grounding<0.9`), and quarantined rows never reach an export. Released datasets are versioned with dataset cards and quality reports.

## A quick look at the shape of it

The lifespan of a dataset in Knovaryn is: **project → source intake → parse (Docling) → structure-aware chunking → plan + dry-run cost estimate → durable run → validation → review → split/version → export → publish.**

Two details worth pulling out:

- **Structure-aware chunking is the default.** Using the Docling tree, heading hierarchy, sentence/token budgets, table boundaries, and neighbor context, it produces chunks that respect document structure — tables stay together, lists stay together. It's deterministic, it's the CI/offline default, and it never makes an undocumented model call.
- **DocETL gather is an optional advanced profile.** For complex collections you can opt into DocETL split/gather behind the same `Chunker` interface. It's gated behind an explicit `docetl` extra and returns canonical chunks like everything else — a documented enhancement with its own cost/quality trade-off, not a hidden dependency.

## MCP-native from the start

We made MCP the primary interface, not an afterthought. The CLI and the MCP server expose the same pipeline: `create_project`, add a source, `plan` with `--dry-run-cost`, `run`, review, `export`. Start `knovaryn mcp` and any MCP-capable agent drives the whole foundry in natural language. The offline demo proves the point: no keys, no network, full pipeline.

## Honest limitations

We want the limitations to be as legible as the features:

- **No bias- or hallucination-freedom claim.** Validation gates grounding and artifact-resistance signals against a *configured policy*. It measures; it does not guarantee correctness or neutrality.
- **No guaranteed improvement.** Knovaryn does not promise that generating a dataset improves any model. Whether training on it helps is a property of your data, your model, and your evaluation — not of the generator.
- **Licensing is a gate, not a law firm.** Knovaryn classifies declared and detected licenses (`allowed` / `review` / `blocked`) and refuses to allow a blocked or unknown source into a public export. That is a useful safety rail, and it is not legal clearance. Do your own review (see the release gate).
- **Quality is relative to your policy and corpus.** A 0.90 grounding floor is a defensible default, not an absolute truth. Benchmark methodology and the release gate document exactly what we do and don't measure.

## Try it

```bash
pip install -e ".[dev]"
knovaryn init
knovaryn mcp --profile offline-demo
```

The 0.1.0 release notes, the reproducible benchmark methodology, and the public 1.0 release gate are in the repo under `docs/marketing/`. The demo script in this same folder walks the full loop in five minutes — including killing a worker mid-run to show a checkpointed resume, and quarantining a weak example with its reason.

We're early, and we'd love contributors: providers, exporters, validators, docling/DocETL profiles, and honest critiques of our quality heuristics. Everything is on GitHub under Apache-2.0.

*— The Knovaryn maintainers*
