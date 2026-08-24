# Guides — MCP Client Setup

Knovaryn's primary interface is a **Model Context Protocol** server with
server ID `knovaryn_mcp`. Any MCP-capable client can drive the whole pipeline
(create a project, add sources, estimate, run, review, export) in natural
language. The server and the CLI expose the same application-services core;
the agent drives tools, Knovaryn owns the durable state.

## Server identity

| Property | Value |
|---|---|
| Server ID | `knovaryn_mcp` |
| Resource URI scheme | `knovaryn://` |
| Env prefix | `KNOVARYN_` |
| Canonical command (stdio) | `knovaryn-mcp` (or `knovaryn mcp`) |
| Remote (Streamable-HTTP) | `knovaryn-mcp --transport streamable-http --host 127.0.0.1 --port 8000` |
| Dev start from a checkout | `uv run knovaryn mcp` |

The **canonical command is `knovaryn-mcp`** — stdio, the default MCP host
transport. The same server is also exposed as the `knovaryn mcp` CLI subcommand
(its flags: `--transport`, `--host`, `--port`, `--database-url`). For a
remote/HTTP deployment, pass `--transport streamable-http` with `--host`/
`--port`. The server instance is identical across transports; only the wire
transport changes.

No credentials are embedded in the client config. The offline demo needs no
keys or network; real providers are configured on the server side via
`KNOVARYN_*` environment variables, never in the MCP client JSON.

## Generic MCP config (JSON)

Most MCP clients accept a JSON list of servers with `command`, `args`, and
`env`. Configure it with the local Python/uv runner:

```json
{
  "mcpServers": {
    "knovaryn_mcp": {
      "command": "uv",
      "args": ["run", "--project", "/absolute/path/to/knovaryn", "knovaryn", "mcp"],
      "env": {
        "KNOVARYN_STATE_DIR": "/absolute/path/to/your/state"
      }
    }
  }
}
```

Notes:

- Real providers are configured through `KNOVARYN_*` env on the *server*
  process — keep those out of client configs unless your client runs the
  process.
- The `--project` working directory must point at the cloned repo so `uv` can
  find the tool. Alternatively install Knovaryn into the active environment and
  use `command: "knovaryn-mcp"` directly.

## Claude Desktop config

Claude-style clients use a top-level `mcpServers` object. Example for a local,
offline install (stdio transport):

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

For a system-wide install where `knovaryn` is on `PATH`:

```json
{
  "mcpServers": {
    "knovaryn_mcp": {
      "command": "knovaryn",
      "args": ["mcp"]
    }
  }
}
```

Keep `env` empty (or minimal) in client config. Real provider keys belong in the
server process environment, not in a JSON config that might be shared or
committed.

## What you can ask the agent

Once connected, natural-language instructions map onto MCP tools:

> "Create project `launch-dataset`, add `./handbook.pdf` (CC0), estimate a run
> of 500 SFT+preference examples, then start it."

The agent calls `knovaryn_create_project`, `knovaryn_add_source`,
`knovaryn_estimate_run` (dry-run cost), and `knovaryn_start_pipeline`, polling
`knovaryn_get_job`. You can also ask it to review a specific example, explain a
rejection reason, or export a version:

> "Show me one rejected preference example and its reason; then export version
> 1.0.0 to TRL and Parquet."

## Transport and compatibility

- Knovaryn declares support for MCP SDKs `mcp>=1.28,<3`. An automated
  acceptance matrix (`scripts/mcp_acceptance_matrix.py`) exercises a clean
  client/server lifecycle on **both supported SDK lines**, over **stdio and
  authenticated streamable HTTP** — see the
  [generated tool reference](../reference/mcp-tools.md) for the live catalogue.
- Handles (`knovaryn://...`) and jobs are explicit and bound to their owner;
  MCP task/progress support is supplementary, not the source of truth.

## Troubleshooting

- Run `knovaryn doctor` first if tools are missing — usually a config or
  extension issue.
- Never put secrets in the client config. If a provider is required, set
  `KNOVARYN_*` in the server's environment and verify with `knovaryn doctor`.
