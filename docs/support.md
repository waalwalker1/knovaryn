# Support & FAQ

## Where to ask

- **Bug reports and feature requests** — [GitHub Issues](https://github.com/waalwalker1/knovaryn/issues).
  Please include the output of `knovaryn doctor --json` (it redacts secrets) and
  the smallest document that reproduces the problem.
- **Security vulnerabilities** — do **not** open a public issue. Follow
  [SECURITY.md](https://github.com/waalwalker1/knovaryn/blob/main/SECURITY.md).
- **Questions and usage help** — [GitHub Discussions](https://github.com/waalwalker1/knovaryn/discussions)
  (enabled by the maintainer; if it is not yet available, open an issue titled
  `question:`).

## Frequently asked questions

### Does the offline demo use a real model?

No. The bundled `knovaryn demo` runs on a deterministic fake provider so the
pipeline mechanics work with no API keys and no network. Its output demonstrates
plumbing, not generation quality — see [Limitations](https://github.com/waalwalker1/knovaryn#12-limitations).
Live generation uses the LiteLLM gateway (`litellm` extra) with provider
credentials from your environment ([providers ADR](adr/0005-litellm-and-providers.md)).

### Why did my export fail with unresolved provenance?

The provenance gate refuses to ship rows whose cited documents/spans cannot be
resolved inside the same project, or whose recomputed content hash differs.
That refusal is deliberate: an export Knovaryn cannot defend never leaves the
building. Inspect the failing rows via lineage
(`GET /v1/projects/{id}/examples/{eid}/lineage` or the `knovaryn_lineage` MCP tool)
and [dataset provenance](concepts/dataset-provenance.md).

### Can multiple workers share one SQLite database?

Concurrent workers need PostgreSQL — the durable-job queue relies on
`SELECT … FOR UPDATE SKIP LOCKED`, which PostgreSQL implements and SQLite's
dialect ignores. Local single-node SQLite mode is local-first and not
multi-writer ([deployment profiles](deployment/profiles.md),
[storage backends ADR](adr/0006-storage-backends.md)).

### Which MCP SDK versions can connect?

Anything speaking the Model Context Protocol within `mcp>=1.28,<3`. Both the
1.x and 2.x lines are exercised over stdio and authenticated streamable HTTP
([MCP clients guide](guides/mcp-clients.md)).

### Where does state live, and how do I back it up?

Under `.knovaryn/` by default (SQLite database + content-addressed artifact
store), overridable through `KNOVARYN_*` environment variables
([configuration reference](reference/config.md)). Use `knovaryn backup` /
`knovaryn restore`; the restore path verifies integrity before completing.

### Is anything published automatically?

No. Publication is dry-run by default and gated on license/privacy policy;
nothing is pushed anywhere without an explicit action
([license & privacy](concepts/license-and-privacy.md)). Note that gating enforces
policy inside Knovaryn — it is not legal clearance for your sources.

### Why do lineage spans show `section` or `chunk` instead of pages?

Location precision reports what the parser actually recorded. PDFs parsed with
the Docling backend carry page/bounding-box precision; Markdown and plain-text
sources honestly report section/chunk granularity rather than fabricating page
numbers ([provenance deep dive](concepts/provenance.md)).
