---
description: >-
  Open-source, MCP-native training-data foundry: turn permitted PDFs and
  documents into traceable, quality-gated SFT, DPO/preference, KTO, and
  evaluation datasets. Every exported example is linked to persisted source
  evidence, quality assessments, review state, version metadata, and
  reproducible release artifacts.
image: assets/knovaryn-banner.svg
---
# Knovaryn

> **Every training example, traced to its source.**

> **New here?** Start with the [Knovaryn MCP ecosystem overview](knovaryn-mcp.md) —
> *"how the whole thing works as a product and service."*

Knovaryn is an **open-source, MCP-native training-data foundry** that turns
*permitted* PDFs and documents into **traceable, quality-gated SFT,
DPO/preference, KTO, and evaluation datasets**.

**Every exported example is linked to persisted source evidence, quality
assessments, review state, version metadata, and reproducible release
artifacts.**

It is local-first by default (SQLite + filesystem) and scales to a team
deployment (PostgreSQL + S3-compatible storage) as a configuration change — not
a code fork.

## What it does

You bring documents you are permitted to use. Knovaryn:

1. **Ingests** them as untrusted data (SHA-256, size, license, privacy preflight).
2. **Parses** them — PDFs and office documents through Docling (optional
   extra; canonical DoclingDocument JSON behind a resource guard), Markdown
   and plain text through built-in parsers — and chunks them
   **structure-aware** (headings, tables, lists, neighbor context).
3. **Plans** a generation profile across topologies (SFT, preference, KTO,
   evaluation) with a **dry-run cost estimate** before anything is spent.
4. **Generates** candidates through a provider-agnostic `ModelGateway`
   (OpenAI-compatible, Anthropic-compatible, DeepSeek) — or a deterministic
   **fake provider** for fully offline, key-free runs.
5. **Validates** every candidate against a dated acceptance policy, attaches
   reason codes, and **quarantines weak examples** so they never export.
6. **Versions, splits, and exports** one canonical dataset to JSONL, Parquet,
   TRL, ShareGPT, Alpaca, OpenAI chat, Hugging Face layout, and evaluation
   formats — the generated table in the
   [exporter reference](reference/exporters.md) is authoritative.

Every accepted example carries evidence references
(`source_document_ids`, `source_span_ids`), a `content_hash`, and generation
candidate IDs — any row can be walked back to its source spans at a
machine-reported location precision (`exact_bbox`, `exact_page`, `page_range`,
`section`, `chunk`) that reflects what the parser actually recorded
([provenance](concepts/provenance.md)).

## Interfaces

All four interfaces sit on the same application-services core:

- **CLI** — `knovaryn` (full command table in the
  [CLI reference](reference/cli.md), generated from the app itself):
  lifecycle groups `project`, `source`, `run`, `job`, `review`, `dataset`,
  plus operational commands `demo`, `init`, `doctor`, `repair`, `backup`,
  `restore`, `server`, `worker`, `mcp`, `verify-release`, `version`.
- **MCP server** — `knovaryn-mcp` (or `knovaryn mcp`); catalogue in the
  [generated tool reference](reference/mcp-tools.md), env prefix `KNOVARYN_`.
  Drive the whole pipeline from any MCP-capable agent.
- **REST control plane** + **local web console** — `knovaryn server`;
  endpoint table in the [generated REST reference](reference/rest-api.md).
- **Python SDK** — the `Workspace` application core.

## Quick links

| Area | Document |
|---|---|
| Product concepts | [Concepts overview](concepts/overview.md) |
| Provenance data model | [Provenance chain](concepts/provenance.md) |
| Quality & quarantine | [Quality & acceptance](concepts/quality.md) |
| Preference data | [Preference-data guidance](concepts/preference-data.md) |
| Architecture | [Overview](architecture/overview.md) · [Pipeline diagram](architecture/diagram.md) · [Jobs](architecture/jobs.md) · [Security](architecture/security.md) |
| Guides | [10-minute offline quickstart](guides/quickstart.md) · [First real project](guides/first-real-project.md) · [MCP clients](guides/mcp-clients.md) |
| Reference | [CLI](reference/cli.md) · [Config](reference/config.md) · [Exporters](reference/exporters.md) · [Claim matrix](reference/claim-matrix.md) |
| Deployment | [Profiles](deployment/profiles.md) · [Docker](deployment/docker.md) |
| Security | [Hardening](security/hardening.md) · [Privacy & licensing](security/privacy-licensing.md) |
| Support | [Support & FAQ](support.md) |
| Landscape | [Peer comparison](peers/index.md) |

## Honest limitations

- Knovaryn measures quality against its configured policy and heuristics; it
  does **not** guarantee the absence of bias or hallucination.
- It does **not** guarantee that a generated dataset improves any model.
- License handling is a safety rail that gates blocked/unknown sources on the
  public path — it is **not** legal clearance.
- This is an alpha (`0.2.1`); APIs are not yet stabilized.

## License

Apache-2.0. Requires Python >= 3.11.
