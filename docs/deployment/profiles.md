# Deployment — Profiles

Knovaryn ships with built-in **profiles** that shift the default configuration
for a given operating context. A profile is selected with `--profile <name>`
(or `profile:` in config) and influences providers, quality floors, storage,
and security posture.

| Profile | Intent | Provider | Storage | Notes |
|---|---|---|---|---|
| `offline-demo` | Credential-free demo | **fake** (deterministic) | SQLite + local | No keys, no network; tolerant on quality to keep the demo flowing. |
| `fast-local` | Fast local iteration | local OpenAI-compatible / fake | SQLite + local | Lower target counts, faster chunks. |
| `balanced` | Default | fake / local / hosted | SQLite (or PG) | Balanced cost/quality. |
| `high-quality` | Stricter quality | hosted | SQLite / PG + S3 | Raises floors, more review, higher budget. |
| `air-gapped` | No network at all | fake / local | SQLite + local | Everything local; no provider egress, telemetry off. |
| `enterprise` | Governed team | hosted via gateway | **PostgreSQL + S3** | Scope-based auth, admin policy enforced, heavier audit/retention. |

## The laptop profile

```bash
uv run knovaryn mcp --profile offline-demo      # quick start
uv run knovaryn run --project <p> --profile fast-local
```

Laptop deployments are **SQLite + local CAS** on `.knovaryn/`. No services to
run; `knovaryn doctor` confirms the environment. Best for the offline demo,
experimentation, and single-user production against a local model.

## The team profile

```bash
uv run knovaryn mcp --profile enterprise
```

Team deployments move storage up the stack:

- **Database:** PostgreSQL (`storage.database_url` → `postgresql+asyncpg://...`).
- **Artifacts:** S3-compatible store (`storage.artifact_backend: s3`).
- **Identity:** OAuth-style resource scopes and admin-enforced policy.

The change is **configuration, not code** (ADR 0006): the same `ArtifactStore`
and repository ports back SQLite + local CAS or PostgreSQL + S3.

## The air-gapped profile

```bash
uv run knovaryn mcp --profile air-gapped
```

For environments with no network:

- Uses the deterministic fake provider or a strictly local model.
- Telemetry/OpenTelemetry disabled and provider egress blocked by policy.
- Everything stays on local storage; no URL ingestion.

Air-gapped is about where you point it, not a separate binary — the same
adapters are used, but network-exposed ones are disabled.

## Profile knobs you can tune

Profiles are starting points. You can override any value in a project or user
config file **without** weakening admin-enforced protected keys. Run
`knovaryn config validate` after editing to confirm what resolved and from
where.

## Choosing

- Just trying it → `offline-demo`.
- Local work with a real model → `fast-local` or `balanced`.
- Regulated / strict QA → `high-quality` (and your own quality policy).
- Forbidden to touch the network → `air-gapped`.
- Multi-user governed team → `enterprise` (see [Docker](docker.md)).
