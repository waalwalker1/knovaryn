---
description: >-
  The product statement and mental model: what Knovaryn is, the
  promises it makes per stage, and an architecture-at-a-glance of
  the whole loop.
title: "Concepts overview"
---

# Concepts — Overview

This page is the product statement, the promises Knovaryn makes, and an
architecture-at-a-glance. The remaining concept pages go deeper on the data
model, quality, and preference data.

## Product statement

> Turn permitted documents into traceable, quality-gated SFT and preference
> datasets that any MCP-capable agent can build, review, and export.

Applied-LLM teams routinely generate "N examples" with no way to show where an
example came from, whether it is any good, or whether the source was usable at
all. Knovaryn treats **evidence** and **acceptance decisions** as first-class
data: every example is linked to its source, and every accepted example earned
its place against a dated policy with a recorded reason.

## The promise

1. **Every training example, traced to its source.** Evidence spans, content
   hashes, and candidate IDs are enforced, not decorative. Exports can carry
   that evidence so a reviewer can inspect the original page/section.
2. **Expensive work is durable.** Jobs run on leased workers with heartbeats,
   checkpoints, and idempotency keys. A killed or disconnected run resumes from
   its last checkpoint without regenerating finished chunks — no duplicate
   token spend.
3. **Bring your own model and trainer.** Providers sit behind a `ModelGateway`
   and exporters emit trainer-native formats. Knovaryn does not lock you in.
4. **Run local or governed.** Offline by default (fake provider, no keys, no
   network); scope-based auth and admin policy for teams.
5. **Measure quality, not merely generate.** Multi-dimension scoring, reason
   codes, and quarantine — weak rows never ship silently.

## Principles

- **Safety and data integrity before convenience.** Untrusted documents are
  handled with strict intake; blocked licenses and high-confidence PII reject
  by default.
- **Determinism where it matters.** The offline demo and CI run on a
  deterministic fake provider; structure-aware chunking is deterministic and
  never makes an undocumented model call.
- **Local-first, team-ready.** The default is SQLite + filesystem; PostgreSQL +
  S3-compatible is a configuration change behind the same `ArtifactStore` and
  repository ports.
- **Canonical core, adapter surface.** The domain model is the single source of
  truth; MCP, CLI, REST, and web are thin interfaces over it.
- **Honest QA.** Quality is *relative to a policy and corpus*. No claim of
  bias-free or hallucination-free output, and no claim that generated data
  improves any model.

## Architecture at a glance

Five layers, all depending inward on the domain:

```
Interfaces (CLI · MCP · REST · Web)
        │  use application/pipeline, never domain internals
Application (project/source/job/export orchestration)
Pipeline    (intake → parse → chunk → plan → generate → validate → version → export)
Domain      (entities, schemas, policies, ports — framework-free)
Infrastructure (SQLite/Postgres, artifact store, Docling, ModelGateway, exporters)
```

The canonical pipeline is documented as a flowchart in
[architecture/diagram.md](../architecture/diagram.md). Job durability is in
[architecture/jobs.md](../architecture/jobs.md); the security posture in
[architecture/security.md](../architecture/security.md).

## The MCP-native control plane

MCP is the primary interface, not a wrapper. `knovaryn_mcp` exposes typed tools
(`create_project`, `add_source`, `plan`, `run`, `review`, `export`, …) that
mirror the CLI verbs. State lives in Knovaryn's durable engine; the agent drives
tools and Knovaryn owns provenance, checkpoints, budgets, and releases. This
division — *agent drives, Knovaryn persists* — is what makes a resumed,
evidence-linked dataset reproducible no matter which client connected.
