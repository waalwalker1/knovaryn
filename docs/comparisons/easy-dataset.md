---
description: >-
  Honest comparison of Knovaryn against Easy Dataset: local LLM
  fine-tune prep vs source-evidenced, quality-gated training-data
  pipelines.
---

# Comparison — Knovaryn vs Easy Dataset

_Factual capability comparison, reviewed 2026-08. Capabilities are "documented
present / absent as of review"; projects move fast, so verify against the live
repos before relying on a claim. See also the [peer landscape](../peers/index.md)._

## What Easy Dataset is

Easy Dataset is a tool for generating and enriching LLM **datasets**. It helps
turn a set of prompts or documents into training/enrichment data, commonly for
instruction tuning and evaluation.

## Where the projects differ

| Concern | Knovaryn | Easy Dataset |
|---|---|---|
| Primary orientation | MCP-native training-data foundry | Dataset generation / enrichment |
| MCP interface | Native `knovaryn_mcp` server | Partial |
| Document → dataset | End-to-end, evidence-linked | Partial |
| Evidence / traceability | Span-level, enforced lineage + content hash | Not centralized |
| Quality gate | Gate validators that quarantine with reasons | Partial |
| Durable resumable jobs | Yes (leased/checkpointed) | No |
| Trainer exports | TRL, LLaMA-Factory, JSONL, Parquet, HF | JSON / others |

Easy Dataset may be a convenient lightweight entry point for ad-hoc dataset
generation. Knovaryn focuses on a **document-grounded, provenance-enforced,
gate-and-export** path with **durable jobs** and a **native MCP** interface for
programmatic and agent-driven dataset construction.

## When to choose Knovaryn

- You want enforced **source lineage** on every example and **fail-closed
  quarantine**.
- You want **resumable jobs** (no re-spending on a crash) and **immutable
  versioned releases**.
- You want to drive construction from an **MCP-capable agent** or a typed REST /
  SDK surface.

## When Easy Dataset may fit better

- You want a minimal, targeted generation/enrichment utility and do not need the
  document foundry, gate, and job layers.

_No superiority claim is implied — the tools differ in scope and depth. See the
[peer landscape](../peers/index.md) for the wider field._
