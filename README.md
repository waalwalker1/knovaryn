<p align="center">
  <b>Knovaryn</b>
</p>
<!-- knovaryn-version: 0.2.1 -->
<!-- Current-release marker (defect 3.5): kept equal to knovaryn.__version__
     by scripts/check_version_sync.py. Update via `python scripts/check_version_sync.py --fix`. -->


<h1 align="center">Knovaryn — open-source, MCP-native training-data foundry</h1>

<p align="center">
  Turn <i>permitted</i> PDFs and documents into <b>traceable, quality-gated SFT,
  DPO/preference, KTO, and evaluation datasets</b> that any MCP-capable agent
  can build, review, and export — <b>every example traced to its source</b>.
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white"/></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache--2.0-blue.svg"/></a>
  <a href="https://modelcontextprotocol.io/"><img alt="MCP" src="https://img.shields.io/badge/MCP-native-orange"/></a>
  <img alt="Offline-first, no API keys" src="https://img.shields.io/badge/offline--first-no%20API%20keys%20required-brightgreen"/>
</p>

<p align="center">
  <a href="https://waalwalker1.github.io/knovaryn/"><strong>Documentation site →</strong></a>
</p>

<p align="center">
  <img src="docs/assets/knovaryn-banner.svg" alt="Knovaryn — from documents to defensible training data" width="100%"/>
</p>

---

## Status

> **Self-hosted open-source alpha (`0.2.1`).** You run it on your own machine or
> infrastructure; there is **no hosted/managed service**. The core pipeline,
> provenance, quality gates, durable jobs, release integrity, and the
> CLI / REST / web console are **stable within the 0.x line** (breaking changes
> documented in the changelog); the MCP tool surface and export formats are
> **experimental** and may still be reshaped before 1.0. The bundled demo runs
> entirely offline on a deterministic fake provider; live model generation and
> certified judge profiles are explicit opt-ins that need real provider
> credentials. Publishing is never automatic — always an explicit, gated action.

---

## 1. Install

One command, no API keys, no network needed to get started:

```bash
pip install knovaryn
```

From source (for development):

```bash
git clone https://github.com/waalwalker1/knovaryn.git
cd knovaryn
uv sync --dev
```

Optional extras are opt-in: `docling`, `docetl`, `litellm`, `s3`, `parquet`,
`hub`, `mcp`, `ml`. See the [configuration reference](docs/reference/config.md).

## 2. 90-second offline demo

The demo runs the complete pipeline on bundled sample documents with a
deterministic fake provider — **no API keys, no network**:

```bash
uv run knovaryn demo --examples 20 --json
uv run knovaryn doctor        # environment + storage health
```

In about 90 seconds you get a release bundle: dataset card, per-file manifest,
quality/source/license/privacy reports, lineage, and a detached checksum.
The full command lifecycle (project → source → run → review → dataset) is in
the [CLI reference](docs/reference/cli.md).

## 3. Real-document quickstart

Point Knovaryn at documents you are permitted to use and drive the pipeline
through the MCP tools (or REST / SDK):

1. `knovaryn_create_project` — create a project.
2. `knovaryn_add_source` — add permitted documents with declared licenses.
3. `knovaryn_estimate_run` — dry-run cost estimate.
4. `knovaryn_start_pipeline` — run SFT / preference / KTO / evaluation.
5. `knovaryn_validate_dataset` — quality gates quarantine failures.
6. `knovaryn_create_dataset_version` + `knovaryn_export_dataset` — ship it.

See [PDF → SFT dataset](docs/guides/pdf-to-sft-dataset.md),
[build DPO preference data](docs/guides/build-dpo-preference-data.md), and
[grounded QA datasets](docs/guides/grounded-qa-dataset-from-documents.md).

## 4. MCP quickstart

Knovaryn is an **MCP training-data server**: a Model Context Protocol server
any MCP-capable agent can drive. The authoritative tool catalogue is generated
from the server registration — see [MCP tools](docs/reference/mcp-tools.md).
Supported MCP SDK range: `mcp>=1.28,<3` (an acceptance matrix exercises both
the 1.x and 2.x lines over stdio and authenticated streamable HTTP).

```
pip install "knovaryn[mcp]"
knovaryn-mcp                     # stdio (default MCP host transport)
# or remote over Streamable-HTTP:
knovaryn-mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

Connect your agent and ask it to build a dataset — see
[MCP training-data server](docs/guides/mcp-training-data-server.md) and
[MCP clients](docs/guides/mcp-clients.md).

## 5. What it produces

A Knovaryn release is an **immutable, versioned bundle**:

- trainer-ready records in JSONL / Parquet and framework layouts (`trl_sft`,
  `trl_preference`, `kto`, `sharegpt`, `alpaca`, `openai_chat`,
  `huggingface_layout`, `evaluation`);
- a dataset card, per-file manifest, quality/source/license/privacy reports;
- a **detached checksum** + reproducible bundle, verified with
  `knovaryn verify-release`.

## 6. Traceability (a concrete example)

Every exported row carries `source_document_ids`, `source_span_ids`, and a
`content_hash`. You can walk any example backward:

```
TrainingExample → chunk → SourceSpan → ParsedDocument → SourceDocument
                                                          → location + precision
```

Every span carries a machine-verifiable **location precision**, derived from
what the parser actually recorded — never asserted by callers: `exact_bbox`
(page + bounding boxes, Docling-backed documents), `exact_page`, `page_range`,
`section`, `chunk`, or `unknown`. Markdown and plain-text sources honestly
report section/chunk granularity instead of fabricating page numbers; lineage
(API `/v1/projects/{id}/examples/{eid}/lineage`, MCP `knovaryn_lineage`) returns
the per-span precision so consumers can verify provenance claims.

The export **provenance gate** resolves every document/span reference to an
existing record in the same project and recomputes the content hash. A row that
cannot be resolved **blocks the export** — Knovaryn never returns a "successful"
export it cannot defend. Export content manifests record the derived precision
of every cited span.

## 7. Quality and policy gates

Candidates are scored against a dated acceptance policy and pass fail-closed
gates — **failure means quarantine, never silent export**:

- **schema** · **grounding** · **completeness/answerability** · **format**
- **refusal** · **duplicate** · **contamination** (train/val/test leakage)
- **semantic consistency** — deterministic contradiction checks
  (`offline-fast`, default), optionally extended by a cited-evidence-only LLM
  judge (`certified-semantic`; deterministic contradictions are final, an
  unavailable judge yields *unverified*, never *verified*)
- **preference signal** (DPO/KTO pairs) and **information gain**
- **privacy** · **license**

Human review (`knovaryn_review_example`) records an approve/reject decision as a
new **immutable revision** — it never mutates an example in place. The gate
list is generated from validator registration:
[quality gates](docs/reference/quality-gates.md); the validation-profile
registry is documented in [validation profiles](docs/reference/profiles.md).

## 8. Supported stack

| Concern | Supported |
|---|---|
| **Inputs** | PDF, Markdown, office/documents (via Docling), local files, archives; URL ingestion opt-in |
| **Topologies** | SFT, DPO/preference, KTO, evaluation (grounded QA) |
| **Exporters** | Generated list in the [exporter reference](docs/reference/exporters.md): JSONL, Parquet, TRL, ShareGPT, Alpaca, OpenAI chat, Hugging Face layout, evaluation |
| **Providers** | Offline deterministic fake provider; LiteLLM gateway (OpenAI-/Anthropic-/DeepSeek-compatible) |
| **Deployment** | Local (SQLite + filesystem); team (PostgreSQL + S3-compatible); Docker / Compose / Kubernetes |
| **Interfaces** | CLI, MCP server, REST + web console, Python SDK |

## 9. Architecture

One **application-services core** behind a durable pipeline engine, exposed
through four interfaces:

```
Source → Parse → Split → Chunk → Generate → Validate → Version → Export → Publish
```

Everything runs as durable jobs (leases, heartbeats, checkpoints, idempotency,
budgets) so a crash resumes instead of redoing paid work. Diagrams (system
architecture, pipeline flow, durable jobs, MCP session, security, value):

**[Architecture at a glance →](docs/architecture/readme-diagrams.md)**

## 10. Security & privacy

- **Offline-first** — no credentials required for the demo, tests, or first run.
- **Secrets from the environment only** — never hard-coded, never logged,
  redacted at the display boundary.
- **Secure intake** — path-traversal/symlink protection, verified archives, URL
  ingestion off by default, SSRF defenses, loopback HTTP binding, no
  shell-command MCP tools.
- **Publication is dry-run by default** and gated on license approval — nothing
  is pushed anywhere without explicit action. See
  [license & privacy](docs/concepts/license-and-privacy.md).

## 11. Benchmarks (methodology & limitations)

Reproducible benchmark suites cover parse fidelity, lineage resolution,
generation validity, groundedness, duplicate/leakage rate, pipeline throughput,
crash recovery, and export compatibility. Semantic-judge quality is measured as
false-accept / false-reject rates with Wilson confidence intervals against an
adversarial corpus. **Honest framing:** offline fake-provider throughput
measures framework overhead only — it is not synthetic-data generation
throughput or model quality. Numbers are versioned with their methodology in
[benchmarks/](benchmarks/) — reproduce them before relying on them.

## 12. Limitations

- **Alpha software**: APIs, storage layout, and the MCP surface may change
  before 1.0; do not build unmanaged long-lived dependencies on 0.x internals.
- The offline demo uses a deterministic fake provider — its output demonstrates
  the pipeline mechanics, not generation quality. Real datasets require real
  providers and your own review effort.
- Location precision depends on what the parser records: plain-text/markdown
  sources cannot yield page or bounding-box precision, and spans are reported
  at the honest lower granularity instead.
- Deterministic semantic checks catch specific contradiction classes only;
  they cannot prove entailment. Judge-based verification requires configured,
  reachable providers and inherits their limitations; unavailable judges fail
  closed to *unverified* rather than guessing.
- Publication gating enforces license/privacy policy inside Knovaryn; it is
  not legal clearance. You are responsible for the rights to your sources.
- Single-node SQLite mode is local-first and not multi-writer; team scale
  expects PostgreSQL plus object storage.

## 13. Comparison — when to choose Knovaryn

Compared factually with related tools (Synthetic Data Kit, Distilabel, Docling,
Easy Dataset) in the [peer landscape](docs/peers/index.md) and
[comparisons](docs/comparisons/synthetic-data-kit.md): choose Knovaryn when you
want a **document-grounded, provenance-enforced, gate-and-export** foundry
driven over **MCP** — not just a parser or a composition SDK.

## 14. Documentation

- [Docs site (MkDocs)](https://waalwalker1.github.io/knovaryn/) ·
  [Guides](docs/guides/quickstart.md) · [Concepts](docs/concepts/overview.md) ·
  [Architecture](docs/architecture/overview.md)
- [Reference — CLI](docs/reference/cli.md) · [Configuration](docs/reference/config.md) ·
  [REST API](docs/reference/rest-api.md) · [MCP tools](docs/reference/mcp-tools.md) ·
  [Quality gates](docs/reference/quality-gates.md) ·
  [Validation profiles](docs/reference/profiles.md) ·
  [Exporters](docs/reference/exporters.md)
- [Claim matrix](docs/reference/claim-matrix.md) — every public claim with its
  maturity, evidence, and known limitation ·
  [Support & FAQ](docs/support.md)
- [README diagrams](docs/architecture/readme-diagrams.md)

## 15. Contributing & community

Please read [CONTRIBUTING.md](CONTRIBUTING.md), the
[code of conduct](CODE_OF_CONDUCT.md), and [SECURITY.md](SECURITY.md). See
[GOVERNANCE.md](GOVERNANCE.md), [ROADMAP.md](ROADMAP.md), and
[CHANGELOG.md](CHANGELOG.md).

## 16. License & citation

**Apache-2.0** for original code (see [LICENSE](LICENSE)). Dataset licensing is
kept separate from code licensing and governed by the source-license registry.
Third-party licenses: [LICENSES-THIRD-PARTY.md](LICENSES-THIRD-PARTY.md).

If you use Knovaryn in research, please cite it — see [CITATION.cff](CITATION.cff).
