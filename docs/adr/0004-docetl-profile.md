# ADR 0004 — DocETL as optional advanced profile

- **Date:** 2026-08-07 · **Status:** Accepted

## Context

DocETL split/gather/map is valuable for complex collections but should not be a
mandatory dependency or default (spec §2.6).

## Decision

- Two chunking/orchestration profiles behind the same interface:
  - `structure_aware` — deterministic default using the Docling tree, heading
    hierarchy, sentence/token budgets, table boundaries, and neighbor context;
  - `docetl_gather` — optional advanced profile using DocETL split/gather.
- `docetl_gather` is only selectable when the `docetl` extra is installed;
  otherwise it raises an explicit `ConfigurationError`. It never makes an
  undocumented model call, translates outputs back to canonical `Chunk`
  records, and supports dry-run estimates.

## Consequence

The deterministic profile is always available and is the CI/offline-demo
default. DocETL is a documented enhancement with its own cost/quality trade-off.
