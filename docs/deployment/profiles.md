---
description: >-
  Deployment profiles: from single-machine SQLite + filesystem to
  PostgreSQL + S3 team deployments — what each profile assumes,
  scales, and limits.
---

# Deployment — Profiles

Knovaryn ships with built-in **profiles** that shift the default configuration
for a given operating context. A profile is selected with the `profile:` config
key (or the `KNOVARYN_PROFILE` environment variable); `knovaryn run` also takes
`--profile` as a per-invocation override. The profile influences providers,
quality floors, storage, and security posture.

| Profile | Intent | Provider | Storage | Notes |
|---|---|---|---|---|
| `offline-demo` | Credential-free demo | **fake** (deterministic) | SQLite + local | No keys, no network; tolerant on quality to keep the demo flowing. |
| `fast-local` | Fast local iteration | local OpenAI-compatible / fake | SQLite + local | Lower target counts, faster chunks. |
| `balanced` | Default | fake / local / hosted | SQLite (or PG) | Balanced cost/quality. |
| `high-quality` | Stricter quality | hosted | SQLite / PG + S3 | Raises floors, more review, higher budget. |
| `air-gapped` | No network at all | fake / local | SQLite + local | Everything local; no provider egress, telemetry off. |
| `enterprise` | Governed team | hosted via gateway | **PostgreSQL + S3** | Scope-based auth, admin policy enforced, heavier audit/retention. |

The profiles move the *same* application core between scales — configuration,
not a fork:

![Knovaryn deployment topology — one access/core/worker/state stack, external model providers, and the three scale profiles](../assets/deployment-topology.png){: width="100%" }

## The laptop profile

```bash
KNOVARYN_PROFILE=offline-demo uv run knovaryn mcp   # quick start
uv run knovaryn run --project <p> --profile fast-local
```

Laptop deployments are **SQLite + local CAS** on `.knovaryn/`. No services to
run; `knovaryn doctor` confirms the environment. Best for the offline demo,
experimentation, and single-user production against a local model.

## The team profile

```bash
KNOVARYN_PROFILE=enterprise uv run knovaryn mcp
```

Team deployments move storage up the stack:

- **Database:** PostgreSQL (`storage.database_url` → `postgresql+asyncpg://...`).
- **Artifacts:** S3-compatible store (`storage.artifact_backend: s3`).
- **Identity:** OAuth-style resource scopes and admin-enforced policy.

The change is **configuration, not code** (ADR 0006): the same `ArtifactStore`
and repository ports back SQLite + local CAS or PostgreSQL + S3.

## The air-gapped profile

```bash
KNOVARYN_PROFILE=air-gapped uv run knovaryn mcp
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
`knovaryn doctor` after editing to confirm the environment resolved as
expected.

## Choosing

- Just trying it → `offline-demo`.
- Local work with a real model → `fast-local` or `balanced`.
- Regulated / strict QA → `high-quality` (and your own quality policy).
- Forbidden to touch the network → `air-gapped`.
- Multi-user governed team → `enterprise` (see [Docker](docker.md)).
