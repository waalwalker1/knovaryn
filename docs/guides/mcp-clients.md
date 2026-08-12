# Guides — MCP Client Setup

Knovaryn's primary interface is a **Model Context Protocol** server,
`knovaryn_mcp`. Any MCP-capable client can drive the whole pipeline (create a
project, add a source, plan, run, review, export) in natural language. The
server and the CLI expose the same verbs; the agent drives tools, Knovaryn owns
the durable state.

## Server identity

| Property | Value |
|---|---|
| Server ID | `knovaryn_mcp` |
| Resource URI scheme | `knovaryn://` |
| Env prefix | `KNOVARYN_` |
| Canonical command (stdio) | `knovaryn-mcp` (or `knovaryn mcp`) |
| Remote (Streamable-HTTP) | `knovaryn-mcp --transport streamable-http --host 127.0.0.1 --port 8000` |
| Typical dev start command | `uv run knovaryn mcp --profile offline-demo` |

The **canonical command is `knovaryn-mcp`** — stdio, the default MCP host
transport. The same server is also exposed as the `knovaryn mcp` CLI subcommand.
For a remote/HTTP deployment, pass `--transport streamable-http` with
`--host`/`--port` (it is hosted on a network service over FastMCP's Starlette
app). The server instance is identical across transports; only the wire
transport changes.

No credentials are embedded in the client config. The offline-demo profile needs
no keys or network; real providers are configured on the server side via
`KNOVARYN_*` environment variables, never in the MCP client JSON.

## Generic MCP config (JSON)

Most MCP clients accept a JSON list of servers with `command`, `args`, and
`env`. Configure it with the local Python/uv runner and the profile you want:

```json
{
  "mcpServers": {
    "knovaryn_mcp": {
      "command": "uv",
      "args": ["run", "--project", "/absolute/path/to/knovaryn", "knovaryn", "mcp", "--profile", "offline-demo"],
      "env": {
        "KNOVARYN_STATE_DIR": "/absolute/path/to/your/state"
      }
    }
  }
}
```

Notes:

- Set `KWRNARYN` profile via `--profile`. For a real provider you would instead
  rely on `KNOVARYN_*` env on the server process — keep those out of client
  configs unless your client runs the process.
- The `--project`/working directory must point at the cloned repo so `uv` can
  find the tool. Alternatively install Knovaryn into the active environment and
  use `command: "knovaryn_mcp"` directly.

## Claude Code / Claude Desktop config

Claude-style clients use a top-level `mcpServers` object. Example for a local,
offline install (stdio transport):

```json
{
  "mcpServers": {
    "knovaryn_mcp": {
      "command": "uv",
      "args": ["run", "knovaryn", "mcp", "--profile", "offline-demo"],
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
      "args": ["mcp", "--profile", "offline-demo"]
    }
  }
}
```

Keep `env` empty (or minimal) in client config. Real provider keys belong in the
server process environment, not in a JSON config that might be shared or
committed.

## What you can ask the agent

Once connected, natural-language instructions map onto MCP tools:

> "Create project `launch-dataset`, add `./fixtures/maintenance-manual-2021.pdf`
> (CC0), plan 500 SFT+preference examples, and run it on the balanced profile."

The agent calls `create_project`, `add_source`, `plan`, `run`, and streams job
events. You can also ask it to review a specific example, explain a rejection
reason, or export a version:

> "Show me one rejected preference example and its reason; then export version
> 0.1.0 to TRL and Parquet."

## Transport and compatibility

- The FastMCP adapter is isolated in `interfaces/mcp/` and feature-detects the
  installed MCP framework (ADR 0002). **stdio** is the fully tested transport.
- MCP changed on **2026-07-28** (sessionless protocol). If your installed
  framework cannot expose a given remote mode, Knovaryn documents that mode as a
  compatibility limit and keeps stdio fully functional.
- Handles (`knovaryn://...`) and jobs are explicit and bound to their owner;
  MCP task/progress support is supplementary, not the source of truth.

## Troubleshooting

- Run `knovaryn doctor` first if tools are missing — usually a config or
  extension issue.
- Determine whether FastMCP exposes the requested transport: `stdio` always;
  remote modes depend on the installed framework version.
- Never put secrets in the client config. If a provider is required, set
  `KNOVARYN_*` in the server's environment and verify with `knovaryn doctor`.
