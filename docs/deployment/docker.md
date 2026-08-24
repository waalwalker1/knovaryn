# Deployment — Docker / Compose

Knovaryn ships container assets under `deploy/`. This page documents the two
primary deployments: a **local** single-container run and a **team** stack of
PostgreSQL + MinIO (S3-compatible) + Knovaryn.

> **Status note:** container assets are provided for operators and exercised by
> CI (`deploy/compose/` is proven end-to-end by
> `tests/deployment/test_compose_e2e.py`; a kustomize base lives under
> `deploy/kubernetes/`). All four interfaces — CLI, MCP server, REST + web
> console, SDK — are available in the container image. The `deploy/` files are
> authoritative for your build.

## Conventions

- Container stem: `knovaryn`.
- Env prefix: `KNOVARYN_` (e.g. `KNOVARYN_STORAGE_DATABASE_URL`,
  `KNOVARYN_STORAGE_ARTIFACT_BACKEND`, `KNOVARYN_PROFILE`).
- Local HTTP control plane binds to loopback by default (`127.0.0.1:8765`);
  in a container expose it only behind an authenticated proxy/TLS.
- Provider keys are injected via environment, never baked into images or
  client config.

## Local (single service)

A minimal container running the MCP server against local storage:

```bash
docker build -f deploy/docker/Dockerfile -t knovaryn .
docker run --rm -it \
  -e KNOVARYN_PROFILE=offline-demo \
  -v "$PWD/.knovaryn:/data" \
  knovaryn mcp
```

Point an MCP client at this container (stdio via `docker run`), or use a
systemd-style launcher for a worker (`knovaryn worker`).

## Team (PostgreSQL + MinIO)

A team deployment moves state rows to PostgreSQL and artifacts to an
S3-compatible store. A Compose file under `deploy/` wires three services:

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: knovaryn
      POSTGRES_USER: knovaryn
      POSTGRES_PASSWORD: ${KNOVARYN_DB_PASSWORD:?set a strong password}
    volumes: ["pgdata:/var/lib/postgresql/data"]

  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER:?set}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD:?set}
    volumes: ["miniodata:/data"]

  knovaryn:
    build: { context: ., dockerfile: deploy/docker/Dockerfile }
    depends_on: [db, minio]
    environment:
      KNOVARYN_PROFILE: enterprise
      KNOVARYN_STORAGE_DATABASE_URL: postgresql+asyncpg://knovaryn:${KNOVARYN_DB_PASSWORD}@db:5432/knovaryn
      KNOVARYN_STORAGE_ARTIFACT_BACKEND: s3
      # S3/MinIO artifact store — these flat storage.* keys are what
      # build_artifact_store reads (see deploy/compose/docker-compose.prod.yml
      # for the full working topology, proven by tests/deployment/).
      KNOVARYN_STORAGE_ENDPOINT_URL: http://minio:9000
      KNOVARYN_STORAGE_BUCKET: knovaryn-artifacts
      KNOVARYN_STORAGE_REGION: us-east-1
      KNOVARYN_STORAGE_ACCESS_KEY_ID: ${MINIO_ROOT_USER}
      KNOVARYN_STORAGE_SECRET_ACCESS_KEY: ${MINIO_ROOT_PASSWORD}
      # writable scratch for the intake quarantine dir (mounted volume; the
      # image runs as non-root uid 10001)
      KNOVARYN_STORAGE_ARTIFACT_ROOT: /data/artifacts
      KNOVARYN_API_TOKEN: ${KNOVARYN_API_TOKEN:?set a strong token}
      KNOVARYN_DEEPSEEK_BASE_URL: ${KNOVARYN_DEEPSEEK_BASE_URL:?set a provider base URL}
    volumes: ["artifacts:/data"]
    ports: ["127.0.0.1:8765:8000"]

volumes:
  pgdata: {}
  miniodata: {}
  artifacts: {}
```

Use `docker compose up -d` (adjust service/file names to your `deploy/` shape).
Secrets come from your environment / a vault, **not** the Compose file.

Environment variables map onto config paths by longest-match against the
config tree (`KNOVARYN_STORAGE_DATABASE_URL` -> `storage.database_url`);
compound leaf names that cannot be recovered by splitting are explicit
aliases in `knovaryn/domain/config.py`. `true`/`false` values coerce to
booleans. A regression suite for this mapping lives in
`tests/security/test_env_config_mapping.py`, and the deployed topology above
is exercised end to end by `tests/deployment/test_compose_e2e.py`
(opt-in: `KNOVARYN_E2E_COMPOSE=1`).

## Running multiple workers

For larger jobs, run one MCP/control container plus several `knovaryn worker`
containers that claim leased jobs from the shared PostgreSQL queue. Because the
job engine leases work with heartbeats and checkpoints, multiple workers can
consume in parallel and a dead worker's jobs are reclaimed after lease expiry.

## Security reminders

- Bind the control plane to loopback and terminate TLS + auth at a reverse
  proxy. Do not expose MinIO or PostgreSQL publicly without protection.
- Do not hard-code secrets in `docker compose` or images; inject via env/vault.
- URL ingestion stays off unless you explicitly enable and SSRF-harden it.
- Sign/setup the DB and S3 buckets per your environment; run `knovaryn doctor`
  inside the container to verify wiring before real runs.

## Air-gapped / offline in containers

For an air-gapped team, run Knovaryn with `KNOVARYN_PROFILE=air-gapped`, use a
strictly local model endpoint, disable URL ingestion and telemetry, and keep all
storage on the private cluster. The image itself is built from your checkout and
does not need public egress.
