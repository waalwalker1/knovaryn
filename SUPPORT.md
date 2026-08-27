# Support

Knovaryn is an open-source community project. We do our best to be helpful, but
we are honest about the boundaries of the support we provide, and there is
**no guaranteed service-level agreement (SLA)**.

## Where to get help

| Need | Where | Notes |
|---|---|---|
| How-to questions, best practices, "is this possible?" | **GitHub Discussions** | The right place for open-ended questions. Search before asking. |
| Bug reports, feature requests, parser regressions, new-exporter requests | **GitHub Issues** — use the relevant [issue template](.github/ISSUE_TEMPLATE/) | Include reproduction, versions, and logs so we can act. |
| Security vulnerabilities | **[SECURITY.md](SECURITY.md)** — private path only | Do **not** open a public issue for a vulnerability. |
| Governance, roles, process questions | a [Discussion](https://github.com/waalwalker1/knovaryn/discussions) | See [GOVERNANCE.md](GOVERNANCE.md). |

## What community support covers

- Reasoning about how to use the CLI, MCP server, REST API, or web console to build
  and export traceable datasets.
- Help diagnosing setup and configuration problems (uv, storage, provider gateways).
- Guidance on the quality gate and provenance model.

## What we can't promise

- **No guaranteed SLA.** Issues are triaged and addressed on a best-effort basis by
  volunteers. Response times vary. If you need a contractual support commitment,
  Knovaryn is not the right vehicle — this project has none.
- **No "we fix it for you" guarantee.** We maintain the codebase, but we can't
  guarantee a bug fix or feature lands within any deadline.
- **No support for unsupported versions.** Only the latest release is supported
  (see [SECURITY.md](SECURITY.md)). Older releases should be migrated.
- **No support for misuse.** We will not advise on ingesting documents you are not
  permitted to use, bypassing safety defaults, or sending secrets through tool
  arguments. That is contrary to the project's design.

## Good first steps before asking

1. Read the [README.md](README.md) and the relevant `docs/` guide.
2. Run `uv run knovaryn doctor` and include its output if something is misconfigured.
3. Run `uv run knovaryn demo --offline --clear` to check that the core workspace
   works on your machine.
4. Search existing issues and Discussions — someone may have already answered.
5. Check the [CHANGELOG.md](CHANGELOG.md) and [ROADMAP.md](ROADMAP.md) to see whether
   a behavior is a known limitation or an upcoming change.

## Etiquette

Be kind and specific. Provide a minimal reproduction, the exact commands you ran,
your Knovaryn version, and relevant logs/redacted config. For a vulnerability, use
the private reporting path — don't leak details in public issues.
