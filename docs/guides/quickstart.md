# Guides — 10-Minute Offline Quickstart

This guide gets a full pipeline running in about ten minutes with **no API keys
and no network**. It uses the deterministic **fake provider** and the
`offline-demo` profile, so install and run are credential-free and reproducible.

## 0. Install (uv)

Install [uv](https://docs.astral.sh/uv/) if you have not already, then install
Knovaryn in a virtualenv:

```bash
cd knovaryn
uv sync --dev            # lean core + dev tooling (no heavy ML extras)
```

The `uv sync` creates `.venv`. Prepend commands with `uv run` (or activate the
venv and drop the prefix). You do **not** need `docling`, `docetl`, `litellm`,
or any model extra for the offline demo.

## 1. Doctor

Check the environment, config, storage, and provider wiring:

```bash
uv run knovaryn doctor
```

This verifies the profile, installed extras, and state directory, and reports
anything misconfigured before you spend time. Fix warnings before continuing.

## 2. Run the bundled offline demo

Run the end-to-end demo to confirm the whole loop works on your machine:

```bash
uv run knovaryn demo --offline --clear
```

`--clear` resets the workspace state so the run is deterministic. It creates a
project, adds a permissive document, plans, runs generation on the fake
provider, and exports — the same loop you now drive by hand.

## 3. Drive the CLI yourself

Now the same pipeline, command by command.

### Create a project

```bash
uv run knovaryn project create \
  --name "Quickstart Dataset" \
  --slug quickstart \
  --description "10-minute walkthrough"
```

### Add a permitted source

```bash
uv run knovaryn source add \
  --project quickstart \
  ./fixtures/maintenance-manual-2021.pdf \
  --declared-license "CC0" \
  --kind upload
```

The source is preflighted (SHA-256, size, page count, license). Inspect it:

```bash
uv run knovaryn source show quickstart --source <id>
```

### Estimate before you spend

```bash
uv run knovaryn plan \
  --project quickstart \
  --topologies sft preference \
  --target 200 \
  --dry-run-cost
```

Nothing is generated yet — this reports predicted chunks, expected tokens
across generator/critic/verifier, estimated cost under the budget, and expected
yield.

### Run

```bash
uv run knovaryn run \
  --project quickstart \
  --profile balanced \
  --topologies sft preference
```

This executes the plan through the job engine (leased worker, checkpoints,
budgets).

### Preview / review

```bash
uv run knovaryn review list --project quickstart --status review --topology sft --limit 1
uv run knovaryn review show --project quickstart --example <id>
uv run knovaryn review list --project quickstart --status review --topology preference --limit 1
uv run knovaryn review show --project quickstart --example <id>
```

Each example shows its evidence block (`source_document_ids`,
`source_span_ids`, content hash) and, for preference pairs, the
`rejected_defect` and preference margin.

### Export

```bash
uv run knovaryn export \
  --project quickstart \
  --version 0.1.0 \
  --format canonical-jsonl \
  --format parquet \
  --format trl-conversational \
  --format llamafactory-sharegpt
```

A single canonical dataset version exported to multiple trainer formats.

## What you just did

permitted document → preflight → plan/estimate → generated, validated examples
→ review with evidence → trainer-ready exports. And it ran entirely offline on
the fake provider.

## Next

- Run the same loop through an MCP client: [MCP clients](mcp-clients.md).
- Start a real project with a local model provider:
  [first real project](first-real-project.md).
