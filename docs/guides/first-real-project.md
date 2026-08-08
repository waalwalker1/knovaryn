# Guides — Your First Real Project

The quickstart runs on the deterministic fake provider. This guide walks a
**real** project: real permitted documents, a **local model provider**, and the
full review/version/export loop. It assumes a local OpenAI-compatible endpoint
(such as Ollama or a local vLLM) is running on `http://127.0.0.1:8080/v1`.

> The same flow works with a hosted provider; a local one just keeps keys
> off the machine and makes cost introspection concrete.

## 1. Configure the provider via environment

Providers are wired through configuration and environment (prefix `KNOVARYN_`).
Point the gateway at your local endpoint:

```bash
export KNOVARYN_DEEPSEEK_BASE_URL="http://127.0.0.1:8080/v1"   # OpenAI-compatible
export KNOVARYN_GENERATOR_MODEL="your-gen-model"
export KNOVARYN_CRITIC_MODEL="your-critic-model"
export KNOVARYN_VERIFIER_MODEL="your-verifier-model"
```

Because `models.*` default to `${KNOVARYN_...}` placeholders, setting these env
vars is enough. Check the wiring:

```bash
uv run knovaryn doctor
```

## 2. Create the project

```bash
uv run knovaryn project create \
  --name "Support-Config Dataset" \
  --slug support-config \
  --description "SFT + preference from internal runbooks (company-permitted)"
```

## 3. Add documents with declared licenses

Add each file you are permitted to use, declaring the license:

```bash
uv run knovaryn source add --project support-config ./docs/runbook-a.pdf --declared-license "internal" --kind local_path
uv run knovaryn source add --project support-config ./docs/runbook-b.md  --declared-license "internal" --kind local_path
uv run knovaryn source inspect --project support-config --source <id>
```

`source inspect` shows the preflight: SHA-256, size, page count, license status,
privacy classification. If a license is `blocked` or `unknown`, content is
gated from public export but (per policy) can still be used for a
non-public path.

## 4. Plan and estimate against the real provider

```bash
uv run knovaryn plan \
  --project support-config \
  --topologies sft preference \
  --target 800 \
  --dry-run-cost
```

The dry run uses your price profile. Because generation is now real and
billable (tokens against a live model), pay attention to estimated cost vs
`budget.maximum_cost_usd` (default 50.00 USD).

## 5. Run

```bash
uv run knovaryn run --project support-config --profile balanced --topologies sft preference
```

In a second terminal, watch progress:

```bash
uv run knovaryn job events --project support-config --job <id> --follow
uv run knovaryn job status --project support-config --job <id>
```

Kill the worker mid-run (Ctrl-C or `kill -TERM`) to see checkpointed resume:

```bash
uv run knovaryn run --resume support-config --job <id>
```

`actual_cost` versus `estimated_cost` is recorded per job, so your spend is
auditable.

## 6. Review with evidence

```bash
uv run knovaryn review list --project support-config --status review --limit 10
uv run knovaryn review show --project support-config --example <id>
# reject weak rows explicitly; accept the good ones
uv run knovaryn review accept --project support-config --example <id>
uv run knovaryn review reject --project support-config --example <id> --reason "grounding<0.9"
```

Examples that failed policy already landed in `rejected` with reason codes and
are excluded from export. Human review refines the `review` set.

## 7. Version and export

```bash
uv run knovaryn dataset validate --project support-config
uv run knovaryn dataset version  --project support-config --semantic 0.1.0
uv run knovaryn export \
  --project support-config --version 0.1.0 \
  --format trl-conversational --format llamafactory-sharegpt --format parquet
```

`dataset validate` re-checks provenance minimums and quality before versioning.

## 8. Inspect lineage and the dataset card

```bash
uv run knovaryn compare        # side-by-side candidate/example comparison
uv run knovaryn dataset card   --project support-config --version 0.1.0
uv run knovaryn dataset lineage --project support-config --example <id>
```

The lineage walks example → generation candidate → chunk → parsed document →
source document → original page/section: the definition of "traceable."

## Notes and honesty

- Quality scores are relative to your configured policy and corpus. A row that
  passes is not a guarantee it improves your model.
- The local endpoint must actually accept the OpenAI-compatible chat schema;
  `knovaryn doctor` surface-tests wiring but not model quality.
- Real runs bill against your provider; keep `budget.maximum_cost_usd` set, and
  never run `--resume` against a billable provider unless you intend to spend.
