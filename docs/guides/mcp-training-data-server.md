# Guide — Knovaryn as an MCP training-data server

Knovaryn is an **MCP-native training-data server**: a Model Context Protocol
server (`knovaryn_mcp`) that any MCP-capable agent — Claude, Cursor, a custom
agent host — can drive to build and export training datasets. "MCP training-data
server" and "Model Context Protocol dataset tools" are its packaging story.

## What the server is

`knovaryn_mcp` is a **23-tool MCP server** exposing the same application-services
core as the CLI, REST API, and SDK. The agent calls tools; Knovaryn owns the
durable state, jobs, provenance, quality gates, and release artifacts.

| Property | Value |
|---|---|
| Server ID | `knovaryn_mcp` |
| Resource URI scheme | `knovaryn://` |
| Env prefix | `KNOVARYN_` |
| Canonical command (stdio) | `knovaryn-mcp` (or `knovaryn mcp`) |
| Remote (Streamable-HTTP) | `knovaryn-mcp --transport streamable-http --host 127.0.0.1 --port 8000` |
| Typical dev start | `uv run knovaryn mcp --profile offline-demo` |

## Install & start

```bash
pip install "knovaryn[mcp]"        # includes the MCP extra / framework
knovaryn-mcp                       # stdio, the default MCP host transport
```

Or from a source checkout:

```bash
uv sync --extra mcp
uv run knovaryn mcp --profile offline-demo
```

## Connect a client

Point your agent at the server. For a source checkout:

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

Keep `env` empty (or minimal) in client config — provider keys belong in the
server process environment, never in a shared/committed JSON file.

## The toolset (what the agent can drive)

The server exposes the full pipeline as tools:

```
health                         knovaryn_create_project      knovaryn_list_projects
knovaryn_add_source            knovaryn_inspect_source      knovaryn_license_report
knovaryn_estimate_run          knovaryn_start_pipeline      knovaryn_get_job
knovaryn_list_jobs             knovaryn_run_job             knovaryn_cancel_job
knovaryn_resume_job            knovaryn_lineage             knovaryn_preview_examples
knovaryn_review_example        knovaryn_validate_dataset    knovaryn_create_dataset_version
knovaryn_export_dataset        knovaryn_publish_dataset     knovaryn_compare_runs
knovaryn_doctor                run_pipeline
```

With it connected you can ask an agent things like:

> "Create project `launch-dataset`, add `./fixtures/maintenance-manual-2021.pdf`
> (CC0), plan 500 SFT+preference examples, and run it on the balanced profile."

or

> "Show me one rejected preference example and its reason; then export version
> `0.1.0` to TRL and Parquet."

## Deployment modes

- **stdio** — the fully tested default, ideal for a local agent session.
- **Streamable-HTTP** — remote/network hosting: point the server at a project
  with real provider config on the server side, and connect over
  `--transport streamable-http --host ... --port ...`.

MCP changed on **2026-07-28** (sessionless protocol); Knovaryn keeps stdio fully
functional and documents any remote-mode compatibility limits honestly (ADR 0002).

## Related

- Guides — [MCP client setup](mcp-clients.md), [first real project](first-real-project.md).
- Concepts — [overview](../concepts/overview.md).
