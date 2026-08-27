---
description: >-
  The compatibility contract that keeps knovaryn-mcp working
  across both maintained MCP SDK major lines, with a tested lower
  bound and cells for current releases.
---

# ADR 0007 — Dual-major MCP SDK compatibility

- **Date:** 2026-08-25 · **Status:** Accepted

Amends the adapter guidance of [ADR-0002](0002-mcp-and-fastmcp.md) (which stays
in force for its isolation rationale) with the tested two-major reality: the
declared dependency range spans **two MCP SDK majors**, `mcp>=1.28,<3`, and
Knovaryn runs its full MCP surface against both.

## Context

ADR-0002 isolated the then-single high-level SDK server behind an internal
boundary. Since then the upstream SDK published major version 2, which renames
the high-level server class and moves the high-level `Context`:

| Concern | SDK 1.x | SDK 2.x |
|---|---|---|
| High-level server | `mcp.server.fastmcp.FastMCP` | `mcp.server.MCPServer` |
| High-level tool/resource `Context` | `mcp.server.fastmcp.Context` | `mcp.server.mcpserver.context.Context` |
| Bundled HTTP client used by `streamable_http_client` | `httpx` | `httpx2` |
| `streamable_http_client(...)` yields | 3-tuple `(read, write, get_session_id)` | 2-tuple `(read, write)` |

Everything else Knovaryn uses is API-identical across both majors. Supporting
only one major would either pin users to a frozen line or break every install
the day their environment resolves `mcp` 2.x, and declaring an unbounded range
without testing both sides would be a claim without evidence.

## Decision

### The single compatibility-adapter boundary

`src/knovaryn/interfaces/mcp/_compat.py` is the **only** module that knows the
SDK split. It exposes:

- `build_mcp_server(name, *, instructions, lifespan)` — constructs the
  high-level server under either name;
- `_context_class()` — resolves the correct `Context` class for the installed
  major;
- `open_streamable_http(url, headers=...)` — client-side Streamable HTTP
  connection that hides the `httpx`/`httpx2` rename and normalizes the yielded
  streams to exactly `(read, write)`;
- `SUPPORTED_MCP_MAJORS = (1, 2)`, `MIN_SUPPORTED_MCP_VERSION = "1.28"`,
  `SERVER_CLS_NAME_1X = "FastMCP"`, `SERVER_CLS_NAME_2X = "MCPServer"`.

`server.py`, the `knovaryn-mcp` entry point, and the tests import the unified
names from this boundary. The declared range in `pyproject.toml`
(`mcp>=1.28,<3`) must stay in lockstep with `SUPPORTED_MCP_MAJORS`.

### Why application logic must not branch on the MCP major

Tool handlers, resources, and the workspace below them are transport- and
SDK-version-free by construction. If any handler tested
`mcp_sdk_major()`, each new SDK point release could silently fork product
behavior, and the acceptance matrix would have to cover a behavioral product
matrix instead of a compatibility matrix. The adapter exists precisely so the
answer to "which SDK am I running on?" appears in exactly one file; a second
place is a defect.

### Context injection behavior

Both majors inspect registered tool/resource signatures and inject the context
object into the parameter annotated with their `Context` class. Because the SDK
evaluates annotations with `eval_str` against the *module globals* of
`server.py`, the module binds `Context = _context_class()` at import time — a
`TYPE_CHECKING`-only alias is deliberately not enough. Handlers receive the
context positionally as their first annotated parameter; nothing else about the
signature contract differs between majors.

One 1.x-only wrinkle handled inside the adapter: 1.x's `Settings` model carries
an unresolved pydantic forward reference that emits
`IncompleteFieldDefinitionWarning` on every server construction. `_compat.py`
calls `Settings.model_rebuild()` once before construction — fixing the warning
at its source rather than filtering it (warnings-as-errors policy).

### Lifespan behavior

Identical semantics on both majors: `build_mcp_server` receives an async
context-manager factory; its `yield` value (the opened `Workspace`) becomes
reachable in every handler as `ctx.request_context.lifespan_context`. On
shutdown the lifespan's `finally` closes the workspace. Combined with the v0.2.1
shutdown-hygiene work (`NullPool` SQLite connections and shielded engine
disposal), teardown produces no post-loop `Event loop is closed` noise even when
the lifespan unwinds inside a cancelled task scope.

### stdio behavior

`knovaryn mcp` / `knovaryn-mcp` defaults to `--transport stdio`, served via
`server.run(transport="stdio")` on both majors. This is the canonical local-host
transport: no network listener, inherits the parent process's stdio, no
authentication material involved.

### Authenticated Streamable HTTP behavior

For `--transport streamable-http` the entry point hosts
`server.streamable_http_app()` under uvicorn, wrapped by `bearer_guard`: when
`server.api_token` is configured, every request without
`Authorization: Bearer <token>` is refused with `401` and
`WWW-Authenticate: Bearer` **before reaching the MCP app** — fail closed. An
empty token keeps the guard as a pass-through, which is only ever legitimate on
a loopback bind (see next section). Clients connect through
`streamable_http_client(url, http_client=...)`, passing custom headers via the
provided HTTP client because both majors route headers that way.

### Non-loopback refusal

`mcp_bind_checked` mirrors the REST J4 policy: binding to anything other than
`127.0.0.1` / `::1` / `localhost` without a configured `server.api_token` raises
`ConfigurationError` at startup — before any socket opens. Explicitly setting
`server.allow_insecure_nonloopback=true` documents a deliberate, unauthenticated,
network-exposed dev server; production exposure goes through the token guard.

### Host/Origin and bearer-token expectations

Stated precisely, because this is where MCP servers most often get oversold:

- The MCP HTTP endpoint performs **no Host-header or Origin allowlisting of its
  own** and sets no cookies; authentication is exclusively the explicit
  `Authorization: Bearer` header, which browser pages cannot attach cross-origin.
- Its safe default is therefore **loopback bind + optional token**: a hostile web
  page cannot reach a loopback-bound socket's responses cross-origin, and any
  wider exposure requires the token guard to be active (enforced by the refusal
  above).
- Operators who reverse-proxy the streamable-HTTP endpoint beyond a trusted
  boundary own the edge policy there — Host allowlist and Origin checks belong
  at that proxy, alongside TLS termination. This matches the deployment guidance
  in [security hardening](../security/hardening.md).
- MCP clients are expected to send the bearer header explicitly (as
  `streamable_http_client` does through its supplied HTTP client). Cookie-based
  or redirect-following auth is neither offered nor accepted.

### Client compatibility assumptions

The acceptance matrix drives Knovaryn with the MCP client stack **bundled in
the same pinned SDK major as the server under test** (`ClientSession` +
`stdio_client` / `streamable_http_client` from that install). That is the
compatibility we claim: an MCP host on SDK 1.x can talk to Knovaryn served by
SDK 1.x, and likewise for 2.x. Cross-major client↔server combinations ride the
wire protocol's own stability and are additionally exercised implicitly — every
cell speaks the same MCP protocol version negotiated at initialize. The driver
normalizes the one structural difference clients see (3-tuple vs 2-tuple stream
yield) in a single helper, mirroring the server-side adapter.

### Clean shutdown guarantees

Every acceptance-matrix stdio run ends with an explicit shutdown check: after
the client session closes, the driver polls up to 10 s and asserts that **no
non-daemon threads leaked** relative to the process baseline. The underlying
guarantees are: the lifespan always closes the workspace (`finally`), engine
disposal is shielded, and SQLite uses `NullPool` — so neither SDK major leaves
dangling event loops, connections, or worker threads behind a normal exit.

### Dependency bounds

- Declared range: `mcp>=1.28,<3`.
- `1.28` is the floor because it is the oldest line actually exercised end to
  end by the matrix; older 1.x releases are neither claimed nor recommended.
- `<3` is the current ceiling. **Widening past it requires adding a
  major-version acceptance cell first** (recorded next to `MATRIX` in
  `scripts/mcp_acceptance_matrix.py`), then extending the adapter if — and only
  if — the new major renamed something this boundary cares about.

### Acceptance-matrix evidence

The executable proof is `scripts/mcp_acceptance_matrix.py` (+ driver
`scripts/mcp_acceptance_driver.py`, wired into CI as the required release-tier
job via `tests/release/test_mcp_acceptance_matrix.py`). Per cell it builds the
wheel once, creates a clean virtualenv, installs the wheel plus the exact pin,
records the exact environment (Python + knovaryn versions, phase 0), verifies
the installed SDK matches the pin, and runs four mandatory phases: full stdio
lifecycle (tool/resource discovery, project → source → pipeline → bounded
preview → lineage, thread-leak check), authenticated Streamable HTTP round trip
plus 401 refusal, and the non-loopback bind refusal.

Matrix executed locally on 2026-08-25 from commit `2bad356` — all cells PASS:

| Pin (role) | Python | knovaryn | Tools | Resource templates | Examples | Leaked threads | stdio | HTTP (401 + round trip) | Bind refusal |
|---|---|---|---|---|---|---|---|---|---|
| `1.28.0` (lower supported boundary) | 3.13.7 | 0.2.1 | 23 | 6 | 3 | none | ok | ok | ok |
| `1.29.1` (latest supported 1.x) | 3.13.7 | 0.2.1 | 23 | 6 | 3 | none | ok | ok | ok |
| `2.0.0` (representative 2.x) | 3.13.7 | 0.2.1 | 23 | 6 | 3 | none | ok | ok | ok |
| `2.1.0` (latest supported 2.x) | 3.13.7 | 0.2.1 | 23 | 6 | 3 | none | ok | ok | ok |

Reproduce with:

```bash
uv run python scripts/mcp_acceptance_matrix.py          # full 4-cell matrix
uv run python scripts/mcp_acceptance_matrix.py --matrix 2.0.0   # one cell
```

(The script needs network access to resolve the pinned SDK versions into fresh
virtualenvs, which is why the CI job owns the canonical run.)

### Deprecation and future-removal policy for 1.x support

- 1.x support is **claimed and tested** while it remains inside the declared
  range; removal follows the changelog, never a silent range bump.
- Dropping 1.x means, in order: (1) a changelog entry under `[Unreleased]`
  announcing the intended removal and the replacement floor, (2) narrowing
  `pyproject.toml` together with `SUPPORTED_MCP_MAJORS`/`MIN_SUPPORTED_MCP_VERSION`
  in the same change, (3) removing the corresponding matrix cell and the 1.x
  branches in `_compat.py`, (4) noting the removal in the MCP guides.
- Until then, a 1.x-only regression blocks release exactly like a 2.x one: the
  acceptance matrix is a required CI job, so a failing cell fails the release.
- If upstream ships a breaking 3.x, the same record governs: acceptance cell
  first, adapter extension second, range widening third.

## Consequences

- Users on either SDK major get the identical tool surface (23 tools,
  `knovaryn://` resource templates) and identical security posture; upgrades of
  the SDK underneath an install are non-events for application code.
- The cost is confined to one small adapter module plus per-cell CI minutes; the
  alternative — branching outside the adapter — was rejected because it makes
  every future handler version-aware.
- Claims stay honest by construction: whatever the matrix does not execute
  (older 1.x floors, hypothetical 3.x) is outside the declared bounds, and the
  [claim matrix](../reference/claim-matrix.md) marks the MCP surfaces
  `experimental` until 1.0 freezes the tool contract.
