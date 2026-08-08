# ADR 0005 — LiteLLM behind ModelGateway

- **Date:** 2026-08-07 · **Status:** Accepted

## Context

LiteLLM normalizes providers but must never appear in domain models. The
`deepseek_flash_budget` profile is a reference, not a hard-coded dependency.

## Decision

- `ModelGateway` port abstracts completion, capability negotiation, structured
  output, caching, fallback, usage capture, and cost ledger persistence.
- Direct SDK mode for local/single-user; optional LiteLLM Proxy profile
  documented for centralized keys/budgets/routing.
- A **deterministic fake provider** is the default for CI, examples, and the
  offline demo. Real provider adapters (OpenAI-compatible; Anthropic-compatible;
  DeepSeek via OpenAI-compatible base URL) are implemented and opt-in.
- Pricing is provided by a dated, overridable price-profile in configuration —
  never hard-coded in domain logic.
- Live provider tests are gated by explicit env flags and a spending cap.

## Consequence

Provider-agnostic runtime; the fake provider keeps the first-contributor
experience credential-free; live providers are first-class but opt-in.
