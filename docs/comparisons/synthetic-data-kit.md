---
description: >-
  Honest comparison of Knovaryn against Meta's Synthetic Data Kit:
  scope, provenance, quality gating, licensing awareness, and
  export layouts.
---

# Comparison — Knovaryn vs Meta's Synthetic Data Kit

_Factual capability comparison, reviewed 2026-08. Capabilities are "documented
present / absent as of review"; projects move fast, so verify against the live
repos before relying on a claim. See also the [peer landscape](../peers/index.md)._

## What Synthetic Data Kit is

Meta's Synthetic Data Kit (SDK) is an open framework for building synthetic-data
generation **agents** — composable components (loggers, wrappers, recipes,
datasets) that turn an LLM into a programmatically steered data generator. It is
a capable, well-maintained foundation for tooling/generating synthetic data over
your own pipelines.

## Where the projects differ

| Concern | Knovaryn | Meta Synthetic Data Kit |
|---|---|---|
| Primary orientation | MCP-native training-data foundry | LLM-data agent framework / SDK |
| MCP interface | Native `knovaryn_mcp` server | No MCP server by default |
| Document → dataset | End-to-end (intake→parse→split→generate→gate→export) | You compose generation yourself |
| Evidence / traceability | Span-level, enforced lineage + content hash | Recorded where you arrange it |
| Quality gate | Gate validators that quarantine with reasons | Where you add components |
| Durable resumable jobs | Yes (leased/checkpointed) | You add your own orchestration |
| Trainer exports | TRL, LLaMA-Factory, JSONL, Parquet, HF | Custom / JSON |

SDK is a great choice when you want to **build your own synthesis pipeline as
code**. Knovaryn is a choice when you want a **batteries-included,
document-grounded, gate-and-export path with enforced provenance** — especially
if you want to drive it over **MCP**.

## When to choose Knovaryn

- You want a document-first pipeline (PDF → SFT / DPO / KTO / QA datasets) with
  enforced source **lineage**.
- You want **quality gates that quarantine** and **resumable jobs** out of the
  box.
- You want to drive dataset construction from an **MCP-capable agent**.

## When SDK may fit better

- You need maximum flexibility to compose your own arbitrary synthesis recipes.
- Your pipeline is fully custom and you do not need the document-foundry layer.

_No superiority claim is implied: both tools are legitimate; they differ in
scope and orientation. See the [peer landscape](../peers/index.md) for the wider
field._
