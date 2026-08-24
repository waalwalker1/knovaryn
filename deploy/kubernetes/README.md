# Knovaryn — Kubernetes deployment (WP K3) & ops runbook

Production manifests for the Knovaryn training-data foundry. The topology runs on
PostgreSQL (shared DB) + MinIO/S3 (content-addressed artifacts) so that **multiple
API replicas and multiple workers share one consistent state**. Local SQLite is a
single-writer, single-machine mode only — it is **not** a safe multi-worker
enterprise queue (spec K1), which is why production uses Postgres.

## Topology

| Resource | Kind | Purpose |
|---|---|---|
| `knovaryn-migrate` | Job | idempotent `create_all` DDL against Postgres |
| `knovaryn-api` | Deployment + Service + HPA | REST API + web console (stateless) |
| `knovaryn-worker` | Deployment | durable pipeline workers (claim→lease→checkpoint) |
| `postgres` | StatefulSet + PVC | shared relational state / queue |
| `minio`, `minio-init` | StatefulSet + PVC, Job | S3-compatible object store + bucket |
| `knovaryn-secrets` | Secret | creds (DB URL, S3 keys, API token) — created by operator |
| `knovaryn-config` | ConfigMap | non-secret app config |
| `default-deny` + ingress/egress rules | NetworkPolicy | network isolation |
| `knovaryn-api` / `knovaryn-worker` | PodDisruptionBudget | availability during drains |

## Deploy

```bash
# 0. Create the Secret (never commit credentials):
kubectl create namespace knovaryn
kubectl -n knovaryn create secret generic knovaryn-secrets \
  --from-literal=db_url='postgresql+asyncpg://knovaryn:CHANGE_ME@postgres:5432/knovaryn' \
  --from-literal=s3_endpoint='http://minio:9000' \
  --from-literal=s3_access_key='CHANGE_ME' \
  --from-literal=s3_secret_key='CHANGE_ME' \
  --from-literal=postgres_password='CHANGE_ME' \
  --from-literal=api_token=''        # set a real token to enforce auth

# 1. Apply everything
kubectl apply -k deploy/kubernetes

# 2. Wait for schema migration + object store init
kubectl -n knovaryn wait --for=condition=complete job/knovaryn-migrate --timeout=120s
kubectl -n knovaryn wait --for=condition=complete job/minio-init --timeout=120s

# 3. Confirm readiness
kubectl -n knovaryn get deploy,pods
```

All images are **pinned to a tagged/digest build** (`…:0.2.1`) — never `latest`
(K3). Pin the app image to a digest in a hardening pass:
`image: ghcr.io/knovaryn/knovaryn@sha256:<digest>`.

## Horizontal scaling (K3 guidance)

- **API**: stateless; scale via HPA on CPU (`api-deployment.yaml`) or
  `kubectl -n knovaryn scale deployment/knovaryn-api --replicas=6`. Safe because
  state lives in Postgres + MinIO.
- **Worker**: interchangeable; each worker holds its own durable lease and
  reruns only un-checkpointed stages on resume (spec §7.3), so
  `kubectl -n knovaryn scale deployment/knovaryn-worker --replicas=8` is safe
  **only against Postgres**. Local SQLite would corrupt/mis-queue under
  concurrent writers — do not scale workers there.
- **Backends**: Postgres/MinIO are single-replica StatefulSets here; scale
  storage separately (managed Postgres, MinIO distributed, or external S3).

## Observability (K4)

- Prometheus metrics: `GET /v1/metrics` (admin-gated, bearer token) —
  job-stage duration/histogram, queue depth, lease-expiry, retries, provider
  errors, cost/tokens, parse throughput, validation rejections, export count,
  publication attempts.
- Structured JSON logs with redaction: never logs source content, generated
  answers, secrets, tokens, or PII by default (`telemetry.content_in_logs=false`).
- OpenTelemetry traces: wire an OTLP exporter via env (see app config);
  trace spans flow from intake → parse → chunk → generate → review → export.

## Backup / restore runbook (K3 + K5)

### Recovery point / time assumptions (K5)

- **RPO (Recovery Point Objective):** the artifact store is content-addressed
  and immutable; a DB+artifact snapshot is a point-in-time backup. Any write
  after backup start is excluded → RPO ≈ time to produce the archive
  (near-zero locally).
- **RTO (Recovery Time Objective):** bounded by archive read + DB restore +
  blob re-validation; sub-second to a few seconds for local SQLite, slightly
  longer for Postgres/S3 depending on volume.
- Restore is a byte-for-byte copy (immutable content), so no migration is
  needed after restore.

### Local mode (SQLite)

```bash
# Backup the whole .knovaryn state dir (DB + artifacts) with a detached checksum
knovaryn backup --out ./backups
# Restore into a clean state dir; verifies DB integrity, refuses non-empty dirs
knovaryn restore --from ./backups/knovaryn-backup-<stamp>.tar.gz
```

`knovaryn backup` writes `knovaryn-backup-<stamp>.tar.gz` plus `…tar.gz.sha256`;
`repair` verifies DB integrity and reconciles missing artifact blobs.

### Kubernetes / Postgres + MinIO

Database:

```bash
# Logical dump while the API/worker pods are quiesced
kubectl -n knovaryn exec deploy/postgres -- \
  pg_dump -U knovaryn -d knovaryn > knovaryn-$(date +%F).sql
# Restore (Postgres must be running, target DB empty)
kubectl -n knovaryn exec -i deploy/postgres -- \
  psql -U knovaryn -d knovaryn < knovaryn-$(date +%F).sql
# For crash-consistent backups use pgBackRest / Velero / cloud snapshots
# on the postgres-data PVC.
```

Object store (artifacts):

```bash
# Full mirror of the bucket to a local dir (or another bucket)
kubectl -n knovaryn exec deploy/minio -- \
  mc alias set target http://localhost:9000 "$S3_ACCESS" "$S3_SECRET"
mc mirror --overwrite --remove /backups/knovaryn-artifacts target/knovaryn-artifacts
```

Alternative: point `storage.artifact_backend` at managed S3 and enable its
versioning/bucket replicas for point-in-time recovery.

### Verify a restore

After restoring, confirm referential integrity: every artifact manifest's
referenced blob resolves and its SHA-256 matches (spec K5), and the DB opens
(`knovaryn doctor` / `PRAGMA integrity_check`). The backup module enforces a
per-file manifest check and fails closed on any checksum mismatch.
