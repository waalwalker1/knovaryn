---
name: Pull request
about: Propose a change to Knovaryn
title: ""
labels: []
assignees: ""
---

## Summary

<!-- What does this change do, and why? One paragraph. Link any related issues. -->

Closes #<!-- issue number, if any -->

## Type of change

<!-- Check all that apply. -->

- [ ] Bug fix
- [ ] New feature or improvement
- [ ] Documentation
- [ ] Dependency change
- [ ] Refactor / no behavior change
- [ ] Release / changelog

## Checklist

<!-- Please be honest. CI runs these checks; ticking a box you haven't done will
be caught in review. -->

**Code quality**
- [ ] I ran the local gate: `make check` (or `ruff check`, `ruff format --check`,
      `mypy`, `pytest -m "not live"`).
- [ ] My commits are signed off (DCO, `git commit -s`) — required for merge.
- [ ] I updated `CHANGELOG.md` under `Unreleased` for user-visible changes.
- [ ] New modules/flags/types are typed and follow the style in `pyproject.toml`.

**Tests**
- [ ] I added or updated tests covering the change.
- [ ] Opt-in tests use the `live`/`docling`/`docetl`/`s3` markers and **skip
      cleanly** without external credentials or extras.
- [ ] Coverage is maintained or improved (threshold: 70% branch on `knovaryn`).

**Data / license impact** (important for a training-data foundry)
- [ ] No copyrighted source material is embedded without license resolution.
- [ ] Any changes to provenance, split, version, or export preserve full source
      tracing for every example.
- [ ] If behavior or safe defaults are affected, a relevant ADR under `docs/adr/`
      is added/updated (see GOVERNANCE.md §5).

**Security**
- [ ] I considered whether this touches intake, auth, secret handling, or parsing
      of untrusted documents. If so, it will need **two** maintainer approvals.
- [ ] No secrets are introduced in code, and logging redaction is preserved.
- [ ] No shell-command MCP tool or unsafe URL/SSRF behavior was added.

**Breaking changes**
- [ ] This change does **not** break the CLI, REST, MCP, web, or exporter surface.
- [ ] If it does break a surface, the migration/announcement is documented in
      `CHANGELOG.md` and (if schema/interface) a new ADR is referenced.

## Test plan

<!-- What did you run to verify this works? Paste relevant output. -->

```bash

```

## Screenshots / logs (optional)

<!-- If this touches the web console, CLI, or MCP output, show before/after. -->
