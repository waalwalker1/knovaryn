---
description: >-
  How Docling document parsing produces canonical artifacts under
  memory/time guardrails so untrusted PDFs cannot exhaust
  resources.
---

# ADR 0003 — Docling canonical artifacts and resource guard

- **Date:** 2026-08-07 · **Status:** Accepted

## Context

Docling is the default parser. Its output is not infallible. The old scaffold
relied on a private `result.input._backend.unload()` call that is not a stable
public contract.

## Decision

- Persist the **DoclingDocument JSON** as the canonical parsed artifact.
  Markdown, plain text, tables, thumbnails are derived artifacts. Never claim
  error-free extraction.
- Implement `DoclingResourceGuard` in one adapter module:
  1. prefer a public release / context-manager API when available;
  2. otherwise guarded feature detection for a private unload;
  3. log which cleanup path was used;
  4. drop references and invoke gc only after artifacts are persisted;
  5. expose a memory regression test;
  6. support worker recycling (`worker_recycle_documents`).
- Docling configuration is selected version-aware and validated at startup;
  unsupported settings fail with a precise message rather than being ignored.
- When the `docling` extra is not installed, the parser path degrades to a
  documented safe adapter (e.g., plain-text/markdown fallback) so intake and the
  offline demo still function.

## Consequence

Memory-safe parsing with a stable adapter boundary; heavy Docling is an opt-in
extra that does not block the lean core.
