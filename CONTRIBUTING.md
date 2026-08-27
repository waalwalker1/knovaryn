# Contributing to Knovaryn

Thanks for your interest in Knovaryn — an open, MCP-native training-data foundry.
We build traceable, quality-gated SFT and preference datasets, and every example
is traced to its source. This file explains how to set up your environment, meet
our quality bar, and get your work reviewed and merged.

Please also read:

- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) — our community standards.
- [GOVERNANCE.md](GOVERNANCE.md) — how decisions are made and roles work.
- [SECURITY.md](SECURITY.md) — how to report vulnerabilities *privately*.
- `docs/adr/` — the Architecture Decision Records that constrain the codebase.

---

## 1. Developer setup

Knovaryn uses **uv** for dependency management and Python **3.11+** (target 3.12,
the supported baseline). A `uv.lock` is committed; always use `uv` so the lockfile
stays authoritative.

```bash
# Install the project with dev dependencies
uv sync --dev

# Install the pre-commit hooks (ruff, ruff-format, mypy, style checks)
uv run pre-commit install
```

Optional heavy/ML extras (Docling, DocETL, LiteLLM, S3, Parquet, Hugging Face Hub)
are **not** required for the offline demo or CI, which use the deterministic fake
model provider:

```bash
# If you need the ML/remote extras locally
uv sync --all-extras --dev
```

You can validate your environment quickly:

```bash
uv run knovaryn doctor     # checks config, storage, provider wiring
uv run knovaryn demo --offline --clear   # fast end-to-end offline demo
```

> Linux/macOS are the primary development targets. Windows is supported for the
> core workspace but remote/heavy extras may be unavailable there.

## 2. Running tests

```bash
uv run pytest                  # everything, including opt-in live tests
uv run pytest -m "not live"    # default CI path — skips network/external-credential tests
uv run pytest -m "not live and not docling and not docetl and not s3"  # fastest subset
```

Key test conventions (mirrored from `pyproject.toml`):

- Tests live under `tests/`, with async mode auto-configured (`asyncio_mode = "auto"`).
- **Opt-in markers** gate anything requiring external credentials or heavy extras:
  `live`, `docling`, `docetl`, `s3`. Such tests **must skip cleanly** when their
  dependencies or env vars (e.g. `DEEPSEEK_API_KEY`, `HF_TOKEN`) are absent — never
  fail hard or hang.
- The offline demo and full CI suite run entirely on the deterministic fake provider
  and local storage. Do not commit tests that require a real provider to pass CI.
- Coverage threshold is **70%** branch coverage on `knovaryn`; new code is expected
  to add or maintain coverage, and untested paths in merge requests will be flagged.

Run coverage locally:

```bash
uv run pytest -m "not live" --cov=knovaryn --cov-report=term-missing
```

## 3. Code style and typing

We enforce style and static typing so that every contribution reads as part of
one system.

```bash
uv run ruff check src tests            # lint
uv run ruff format --check src tests   # formatting check
uv run ruff format src tests           # apply formatting
uv run mypy src/knovaryn               # type check (tests excluded by config)
```

- **ruff**: line length 100, ruleset `E F I W B UP C4 SIM` (`B008` ignored), from
  `pyproject.toml`.
- **mypy**: strict-ish settings — `disallow_untyped_defs`, `warn_return_any`,
  `strict_equality`, `no_implicit_optional`, `warn_unused_ignores`, and more. New
  modules must be fully typed. Migrations, tests, and benchmarks are excluded.
- The pre-commit hooks run ruff (with `--fix`) and mypy automatically; make sure
  `git commit` passes them before pushing.

The one-shot `make check` runs the full local gate:

```bash
make check   # lint + format + type + test + docs-build + build
```

CI runs essentially the same gate plus dependency/container/secret and static-analysis
scans.

## 4. Testing standards

Good changes come with good tests. When you touch code, add or update tests that:

- exercise the **domain and pipeline** behavior through the public ports, not just
  implementation details;
- verify **traceability and provenance** (the product promise) — e.g. that an example
  retains its source, version, and lineage through split/export;
- verify **safety defaults** (unknown license → `review`; URL ingestion off by
  default; secret redaction; no shell commands), since Knovaryn treats source
  documents as untrusted data (spec §8.6);
- cover the new public interface (CLI, REST, MCP, web) at least at the handler level;
- include a **regression test** for any bug you fix.

When you change control flow for datasets, add a small golden fixture or verified
expected output rather than only fuzzy assertions.

## 5. Submitting a pull request

1. **Discuss first (optional but recommended)** for large or design-heavy changes —
   open a discussion or an issue so you get early feedback before writing a lot of code.
2. **Create a branch** off `main` (never commit to `main` directly).
3. **Keep changes focused.** Split unrelated changes into separate PRs. A PR should
   do one thing.
4. **Run the full local gate** before opening:
   `make check` (or at minimum `ruff check`, `ruff format --check`, `mypy`, `pytest -m "not live"`).
5. **Open the PR** using the [pull request template](.github/pull_request_template.md).
   Fill in every checkbox honestly, including the **data/license impact** and
   **security** sections.
6. **Add a changelog entry** under `Unreleased` in `CHANGELOG.md` for user-visible
   changes, following Keep a Changelog.
7. **Decisions that constrain the project** (new dependencies, interface changes,
   license/parsing behaviors, security posture) should reference or add an
   Architecture Decision Record under `docs/adr/` (§5 in GOVERNANCE.md explains when).

### Review process

- At least **one maintainer** approves; two are required for anything that changes
  security-sensitive code, dependency baselines, or the release gate (§5, §7 in
  GOVERNANCE.md).
- Keep your branch up to date with `main`; reviewers may ask for history cleanup,
  but **never force-push to shared branches** others use.
- Reviews are expected to be **timely and kind** — give actionable feedback, use
  suggestions where possible, and acknowledge good work.

## 6. Release and dependency freeze

- Releases are cut by the release manager from `main` (see [GOVERNANCE.md](GOVERNANCE.md)).
- Dependency additions go through the **dependency baseline** ADR
  (`docs/adr/0001-dependency-baseline.md`) — don't add a dependency casually or
  "because it's handy." Present scope, license, maintenance status, and supply-chain
  risk in the PR.
- Never accept a provider key or secret through code; all secrets stay in environment
  variables or the configured secrets store, and are redacted in logs.

## 7. Issue and PR etiquette

- **Search before filing** — duplicate issues slow everyone down. Comment on the
  existing issue instead.
- Use the **issue templates** (bug report, feature request, parser regression,
  new exporter) — they ask for exactly the information their reviewers need.
- **Security issues** must NOT be filed as public issues. Use the private path in
  [SECURITY.md](SECURITY.md) (GitHub private vulnerability reporting).
- Be responsive to review feedback; if a PR goes stale for 30+ days without
  activity it may be closed to keep the queue healthy. You can always reopen it.

## 8. Documentation

- User-facing docs live under `docs/` and are built with **MkDocs**.
- Rebuild and preview locally before opening a docs PR:

```bash
uv run mkdocs serve      # live preview
uv run mkdocs build      # static build
```

- Cross-cutting or product-level behavior belongs in `docs/architecture/` and
  `docs/adr/`; quick answers belong in the relevant guide under `docs/guides/`.

## 9. Legal: DCO and licensing

Knovaryn is **Apache-2.0** licensed, and all contributions must be compatible with
that license.

- **Developer Certificate of Origin (DCO):** by contributing you agree to the terms
  of the [Developer Certificate of Origin](https://developercertificate.org/).
  Sign off your commits with `git commit -s` (this adds a
  `Signed-off-by: Your Name <you@example.com>` trailer). Commits without a
  `Signed-off-by` trailer cannot be accepted.
- If your contribution includes code or text copied from another project, confirm
  the source is license-compatible with Apache-2.0 and note it in the PR. Never
  include content you are not licensed to contribute.
- **Data contributions** should never embed copyrighted source material as
  training examples unless it is explicitly permitted and license-resolved through
  the normal pipeline — that tracing is the entire point of Knovaryn.

If you have a question about licensing your contribution, ask a maintainer before
submitting.

## 10. Getting help

- Ask questions in GitHub **Discussions** — they're for "how do I", not bug reports.
- File **bugs** as issues using the bug report template.
- For **security**, follow [SECURITY.md](SECURITY.md).

Thank you for helping make Knovaryn a place where every training example can be
traced to its source.
