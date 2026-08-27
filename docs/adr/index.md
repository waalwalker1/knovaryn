---
description: >-
  Index of Knovaryn architecture decision records: dependency
  baseline, MCP adapter isolation, Docling guards, storage
  backends, SDK compatibility.
---

# Architecture Decision Records

| ADR | Title | Status |
|---|---|---|
| [0001](0001-dependency-baseline.md) | Dependency baseline and environment strategy | Accepted |
| [0002](0002-mcp-and-fastmcp.md) | MCP 2026-07-28 and FastMCP adapter isolation | Accepted (amended by [0007](0007-dual-major-mcp-sdk-compatibility.md)) |
| [0003](0003-docling-resource-guard.md) | Docling canonical artifacts and resource guard | Accepted |
| [0004](0004-docetl-profile.md) | DocETL as optional advanced profile | Accepted |
| [0005](0005-litellm-and-providers.md) | LiteLLM behind ModelGateway | Accepted |
| [0006](0006-storage-backends.md) | SQLite/PostgreSQL and local/S3 artifact backends | Accepted |
| [0007](0007-dual-major-mcp-sdk-compatibility.md) | Dual-major MCP SDK compatibility (`mcp>=1.28,<3`) | Accepted |

Decisions follow the spec priority (§0.2): safety/data integrity > official MCP
spec > official library docs > required behavior > convenience.
