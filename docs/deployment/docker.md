# Deployment — Docker / Compose

Knovaryn ships container assets under `deploy/`. This page documents the two
primary deployments: a **local** single-container run and a **team** stack of
PostgreSQL + MinIO (S3-compatible) + Knovaryn.

> **Status note:** container assets are provided for operators. In the 0.1.0
> alpha the CLI and MCP server remain the supported interfaces; Docker packages
> the same binary so a team can run the MPI-server/worker on containers. Treat
> YAML below as the documented shape, and confirm against your build's
> `deploy/` files, which are authoritative.

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
docker build -f deploy/Dockerfile -t knovaryn .
docker run --rm -it \
  -e KNOVARYN_PROFILE=offline-demo \
  -v "$PWD/.knovaryn:/data" \
  knovaryn mcp --profile offline-demo
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
    build: { context: ., dockerfile: deploy/Dockerfile }
    depends_on: [db, minio]
    environment:
      KNOVARYN_PROFILE: enterprise
      KNOVARYN_STORAGE_DATABASE_URL: postgresql+asyncpg://knovaryn:${KNOVARYN_DB_PASSWORD}@db:5432/knovaryn
      KNOVARYN_STORAGE_ARTIFACT_BACKEND: s3
      KNOVARYN_S3_ENDPOINT: http://minio:9000
      KNOVARYN_S3_BUCKET: knovaryn-artifacts
      AWS_ACCESS_KEY_ID: ${MINIO_ROOT_USER}
      AWS_SECRET_ACCESS_KEY: ${MINIO_ROOT_PASSWORD}
      KNOVARYN_DEEPSEEK_BASE_URL: ${KNOVARYN_DEEPSEEK_BASE_URL:?set a provider base URL}
    ports: ["127.0.0.1:8765:8765"]

volumes:
  pgdata: {}
  miniodata: {}
```

Use `docker compose up -d` (adjust service/file names to your `deploy/` shape).
Secrets come from your environment / a vault, **not** the Compose file.

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
