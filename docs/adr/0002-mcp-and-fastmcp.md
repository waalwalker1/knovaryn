# ADR 0002 — MCP 2026-07-28 and FastMCP adapter isolation

- **Date:** 2026-08-07 · **Status:** Accepted

## Context

MCP changed on 2026-07-28 (sessionless protocol). FastMCP 4 may be beta. The
spec requires isolating FastMCP-specific APIs in `interfaces/mcp/` and never
spreading version-specific context APIs across domain/pipeline.

## Decision

- Application state is the **source of truth**: projects, jobs, review handles,
  and dataset versions are explicit, server-minted handles bound to the owner.
  MCP task/progress support is supplementary.
- FastMCP is confined to `src/knovaryn/interfaces/mcp/`. A compatibility layer
  adapts to whatever FastMCP version is actually installed at runtime (feature
  detection on the init/protocol entrypoint), and contract tests cover tool
  schemas, stdio cleanliness, and modern Streamable HTTP to the available
  framework capability.
- The MCP server ID is `knovaryn_mcp` and resource URIs use `knovaryn://`.

## Consequence

MCP interface changes do not leak into the domain or pipeline. If the installed
FastMCP cannot expose a given remote mode, the mode is documented as a
compatibility limit and stdio remains fully tested.
