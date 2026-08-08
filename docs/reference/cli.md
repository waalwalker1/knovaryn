# Reference — CLI

The CLI (`knovaryn`) exposes the same pipeline as the MCP server and REST
control plane. Run with `uv run knovaryn ...`. Global flags include
`--profile`, `--config <path>`, and `--project <slug-or-id>` where applicable.

## Setup and checks

| Command | Purpose |
|---|---|
| `knovaryn --version` | Print version (e.g. `0.1.0`). |
| `knovaryn init` | Create the `.knovaryn/` state directory and default config. |
| `knovaryn doctor` | Check profile, extras, config, storage, and provider wiring. Run this first. |
| `knovaryn config validate` | Validate a config file against the schema and report value provenance. |

## Projects

| Command | Purpose |
|---|---|
| `knovaryn project create --name <n> [--slug <s>] [--description <d>]` | Create a project (the container and authorization boundary). |
| `knovaryn project list` | List projects (`--limit`, cursor pagination). |

## Sources

| Command | Purpose |
|---|---|
| `knovaryn source add --project <p> <path> [--declared-license <l>] [--kind upload\|local_path\|url\|repository\|dataset]` | Ingest a permitted document; preflights SHA-256, size, page count, license, privacy. |
| `knovaryn source inspect --project <p> --source <id>` | Show intake preflight: license status, privacy classification, artifacts. |
| `knovaryn source show --project <p> --source <id>` | Alias for inspecting a single source's details. |

## Plan / estimate

| Command | Purpose |
|---|---|
| `knovaryn plan --project <p> --topologies sft preference [--target <n>] [--dry-run-cost]` | Build the generation plan and, with `--dry-run-cost`, report estimated cost under budget. No model calls. |
| `knovaryn estimate --project <p> [--target <n>]` | Standalone cost/yield estimate for the current plan. |

## Run

| Command | Purpose |
|---|---|
| `knovaryn run --project <p> [--profile <profile>] [--topologies <list>]` | Execute the plan through the durable job engine. |
| `knovaryn run --resume <p> --job <id>` | Resume a paused/failed job from its last checkpoint. |

## Jobs

| Command | Purpose |
|---|---|
| `knovaryn job status --project <p> --job <id>` | Show state, current stage, progress, error, estimated/actual cost. |
| `knovaryn job events --project <p> --job <id> [--follow]` | Stream the append-only structured event log. |
| `knovaryn job cancel --project <p> --job <id>` | Cooperative cancellation (flushes checkpoints before stopping). |
| `knovaryn job resume --project <p> --job <id>` | Explicitly retry a failed job or resume a paused one. |

## Review / preview

| Command | Purpose |
|---|---|
| `knovaryn review list --project <p> [--status review\|rejected\|accepted] [--topology sft\|preference\|kto\|evaluation] [--reason <code>] [--limit <n>]` | List examples with a filter (e.g. `--reason grounding<0.9`). |
| `knovaryn review show --project <p> --example <id>` | Inspect one example including its evidence block and quality dimensions. |
| `knovaryn review accept --project <p> --example <id>` | Accept a reviewed example. |
| `knovaryn review reject --project <p> --example <id> --reason <code>` | Reject (quarantine) an example with an explicit reason. |
| `knovaryn example preview --project <p> [--id <id>]` | Preview generated examples/candidates before acceptance. |

## Datasets / version / export / publish

| Command | Purpose |
|---|---|
| `knovaryn dataset validate --project <p>` | Re-check provenance minimums and quality before versioning. |
| `knovaryn dataset version --project <p> --semantic <v> [--parent <id>]` | Freeze a snapshot (draft). |
| `knovaryn dataset card --project <p> --version <v>` | Show the dataset card (counts, source/license/quality reports). |
| `knovaryn dataset lineage --project <p> --example <id>` | Walk example → candidate → chunk → parsed → source → page/section. |
| `knovaryn export --project <p> --version <v> [--format <f> ...]` | Export one canonical version to trainer formats. |
| `knovaryn dataset publish --project <p> --version <v> [--confirm <token>]` | Publish (gated by license/privacy reports; confirmation required). |
| `knovaryn compare --project <p>` | Side-by-side comparison of candidates/examples for review. |

## Server / worker / demo / benchmark

| Command | Purpose |
|---|---|
| `knovaryn server mcp --profile <p>` | Start the MCP server (`knovaryn_mcp`; stdio, plus remote modes per framework). |
| `knovaryn server web [--bind 127.0.0.1] [--port 8765]` | Start the REST control plane + local web console (partial in 0.1.0). |
| `knovaryn worker [--project <p>]` | Start a durable job worker that claims leased jobs. |
| `knovaryn demo --offline [--clear]` | Run the credential-free, network-free end-to-end demo. |
| `knovaryn benchmark [--methodology <path>]` | Run the reproducible benchmark harness (see `benchmark-methodology.md`). |

## Notes

- Command lines above normalize shorthand used across the demo scripts; run
  `knovaryn <command> --help` for the authoritative flag set for your build.
- Events and jobs are durable — `job cancel` and `run --resume` are safe against
  crashes and do not double-spend provider tokens.
- `demo --offline` works entirely on the fake provider; `benchmark` numbers are
  only meaningful when reproduced with the documented methodology.
