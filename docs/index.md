# Knovaryn

> **Every training example, traced to its source.**

Knovaryn is an **open-source, MCP-native training-data foundry**. It converts
*permitted* source documents into **traceable, quality-gated SFT and preference
datasets** that any MCP-capable agent can build, review, and export.

It is local-first by default (SQLite + filesystem) and scales to a team
deployment (PostgreSQL + S3-compatible storage) as a configuration change — not
a code fork.

## What it does

You bring documents you are permitted to use. Knovaryn:

1. **Ingests** them as untrusted data (SHA-256, size, license, privacy preflight).
2. **Parses** them with Docling (canonical DoclingDocument JSON, with resource
   guards) and chunks them **structure-aware** (headings, tables, lists,
   neighbor context).
3. **Plans** a generation profile across topologies (SFT, preference, KTO,
   evaluation) with a **dry-run cost estimate** before anything is spent.
4. **Generates** candidates through a provider-agnostic `ModelGateway`
   (OpenAI-compatible, Anthropic-compatible, DeepSeek) — or a deterministic
   **fake provider** for fully offline, key-free runs.
5. **Validates** every candidate against a dated acceptance policy, attaches
   reason codes, and **quarantines weak examples** so they never export.
6. **Versions, splits, and exports** one canonical dataset to TRL,
   LLaMA-Factory ShareGPT, OpenAI chat, ShareGPT, Alpaca, Parquet, and Hugging
   Face.

Every accepted example carries evidence references
(`source_document_ids`, `source_span_ids`), a `content_hash`, and generation
candidate IDs — so any row can be walked back to the exact page and section it
came from.

## Interfaces

- **CLI** — `knovaryn` (commands: `init`, `doctor`, `project`, `source`,
  `plan`, `run`, `job`, `review`, `dataset`, `export`, `compare`, `server`,
  `worker`, `demo`, `benchmark`, `config`).
- **MCP server** — `knovaryn_mcp`, resource URIs `knovaryn://`, env prefix
  `KNOVARYN_`. Drive the whole pipeline from any MCP-capable agent.
- **REST control plane** + **local web console** (partial in 0.1.0; the CLI and
  MCP server are the supported interfaces today).

## Quick links

| Area | Document |
|---|---|
| Product concepts | [Concepts overview](concepts/overview.md) |
| Provenance data model | [Provenance chain](concepts/provenance.md) |
| Quality & quarantine | [Quality & acceptance](concepts/quality.md) |
| Preference data | [Preference-data guidance](concepts/preference-data.md) |
| Architecture | [Overview](architecture/overview.md) · [Pipeline diagram](architecture/diagram.md) · [Jobs](architecture/jobs.md) · [Security](architecture/security.md) |
| Guides | [10-minute offline quickstart](guides/quickstart.md) · [First real project](guides/first-real-project.md) · [MCP clients](guides/mcp-clients.md) |
| Reference | [CLI](reference/cli.md) · [Config](reference/config.md) · [Exporters](reference/exporters.md) |
| Deployment | [Profiles](deployment/profiles.md) · [Docker](deployment/docker.md) |
| Security | [Hardening](security/hardening.md) · [Privacy & licensing](security/privacy-licensing.md) |
| Landscape | [Peer comparison](peers/index.md) |

## Honest limitations

- Knovaryn measures quality against its configured policy and heuristics; it
  does **not** guarantee the absence of bias or hallucination.
- It does **not** guarantee that a generated dataset improves any model.
- License handling is a safety rail that gates blocked/unknown sources on the
  public path — it is **not** legal clearance.
- This is an alpha (`0.1.0`); APIs are not yet stabilized.

## License

Apache-2.0. Requires Python >= 3.11.
