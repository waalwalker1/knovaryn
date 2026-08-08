# Knovaryn Decision Log (DECISION_LOG.md)

Assumptions, upstream incompatibilities, safe defaults, and ADR links.
Every decision here is a spec-sanctioned interpretation; link to ADRs where applicable.

## Build-time executor

- Spec §0.3 prefers Claude Code + DeepSeek-V4-Flash. This run is executing inside the harness; the build model reported is `deepinfra/deepseek-v4-flash-0731`. The product runtime is provider-agnostic and does NOT depend on DeepSeek.
- The `deepseek_flash_budget` model profile is an optional runtime profile, fully isolated behind `ModelGateway`. CI and offline demo use the deterministic fake provider.
- Live DeepSeek/HF tests are opt-in and skip cleanly without `DEEPSEEK_API_KEY` / `HF_TOKEN`.

## Upstream decisions / compat notes

- **MCP 2026-07-28 + FastMCP:** The spec requires isolating FastMCP. Because of the fast-moving MCP revision and the possibility that FastMCP 4 is pre-release, we implement the MCP server through `interfaces/mcp/` using whatever FastMCP API is actually installed and lock it in the ADR. The Knovaryn job/state model is the source of truth, not MCP progress.
  - ADR: `docs/adr/0002-mcp-and-fastmcp.md`
- **Docling cleanup:** We never call `result.input._backend.unload()` directly. `DoclingResourceGuard` prefers public release/context-manager APIs, uses feature detection for any private unload, logs the chosen path, and enables worker recycling. A memory regression test exists.
  - ADR: `docs/adr/0003-docling-resource-guard.md`
- **DocETL is optional.** `structure_aware` chunking is the default. `docetl_gather` is behind an optional adapter that must be explicitly enabled; when DocETL is not installed it degrades to an explicit, documented guard rather than silently pretending.
  - ADR: `docs/adr/0004-docetl-profile.md`
- **LiteLLM:** wrapped behind `ModelGateway`; direct SDK mode for local use, optional LiteLLM proxy profile documented. Not imported in domain.
  - ADR: `docs/adr/0005-litellm-and-providers.md`
- **Storage:** SQLite (WAL) default, PostgreSQL production; local content-addressed store default, S3-compatible extra. Both behind `ArtifactStore`.
  - ADR: `docs/adr/0006-storage-backends.md`

## Safe defaults adopted

- URL ingestion disabled by default; SSRF protect; loopback HTTP + Host/Origin validation; symlink escape + path traversal rejected; no shell-command MCP tool; secret redaction everywhere.
- Unknown source license => `review` (never `allowed for public release`). Public publication requires `approved` version + resolved licenses + dry-run + confirmation.
- Budgets enforced before exceeding hard limits (`budget_exhausted` pause).

## Known environment constraints (honest)

- This build runs in a macOS sandbox without all ML-heavy extras compiled; Docling/DocETL heavy model downloads are gated behind opt-in extras so the offline demo and full test suite run without them while the real adapters and golden-fallback parsers remain.
- Everything recorded; no hidden "coming soon".
