# Guide — Knovaryn as an MCP training-data server

Knovaryn is an **MCP-native training-data server**: a Model Context Protocol
server (`knovaryn_mcp`) that any MCP-capable agent — Claude, Cursor, a custom
agent host — can drive to build and export training datasets. "MCP training-data
server" and "Model Context Protocol dataset tools" are its packaging story.

## What the server is

`knovaryn_mcp` exposes the same application-services core as the CLI, REST
API, and SDK. The agent calls tools; Knovaryn owns the durable state, jobs,
provenance, quality gates, and release artifacts.

| Property | Value |
|---|---|
| Server ID | `knovaryn_mcp` |
| Resource URI scheme | `knovaryn://` |
| Env prefix | `KNOVARYN_` |
| Canonical command (stdio) | `knovaryn-mcp` (or `knovaryn mcp`) |
| Remote (Streamable-HTTP) | `knovaryn-mcp --transport streamable-http --host 127.0.0.1 --port 8000` |
| Dev start from a checkout | `uv run knovaryn mcp` |

## Install & start

```bash
pip install "knovaryn[mcp]"        # includes the MCP extra / framework
knovaryn-mcp                       # stdio, the default MCP host transport
```

Or from a source checkout:

```bash
uv sync --extra mcp
uv run knovaryn mcp
```

## Connect a client

Point your agent at the server. For a source checkout:

```json
{
  "mcpServers": {
    "knovaryn_mcp": {
      "command": "uv",
      "args": ["run", "knovaryn", "mcp"],
      "cwd": "/absolute/path/to/knovaryn",
      "env": {}
    }
  }
}
```

Keep `env` empty (or minimal) in client config — provider keys belong in the
server process environment, never in a shared/committed JSON file.

## The toolset (what the agent can drive)

The server exposes the full pipeline as tools — project/source lifecycle,
dry-run estimation, durable jobs (start/poll/cancel/resume), example preview,
lineage, immutable-revision review, validation, versioning, export, and a
confirm-gated publish. **The authoritative catalogue is generated from the
server's real registration**: see [MCP tools](../reference/mcp-tools.md).

With it connected you can ask an agent things like:

> "Create project `launch-dataset`, add `./handbook.pdf` (CC0), estimate a run
> of 500 SFT+preference examples, then start it."

or

> "Show me one rejected preference example and its reason; then export version
> `1.0.0` to TRL and Parquet."

## Deployment modes

- **stdio** — default, ideal for a local agent session.
- **Streamable-HTTP** — remote/network hosting behind bearer-token auth: point
  the server at a project with real provider config on the server side, and
  connect over `--transport streamable-http --host ... --port ...`.

Both transports are exercised by the automated MCP acceptance matrix across the
supported SDK range (`mcp>=1.28,<3`) — see the
[tool reference](../reference/mcp-tools.md).

## Related

- Guides — [MCP client setup](mcp-clients.md), [first real project](first-real-project.md).
- Concepts — [overview](../concepts/overview.md).
