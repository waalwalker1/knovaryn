# ADR 0006 — Storage backends

- **Date:** 2026-08-07 · **Status:** Accepted

## Context

Knovaryn must run local (SQLite + filesystem) and team (PostgreSQL + S3) without
locking into a single backend (spec §0.1, §21).

## Decision

- **Database:** SQLAlchemy 2 async + Alembic. SQLite default (WAL, foreign keys,
  documented local concurrency); PostgreSQL production (asyncpg).
- **Artifact store:** content-addressed immutable bytes plus manifest metadata.
  Local CAS default; S3-compatible adapter behind the `s3` extra. Both implement
  the same `ArtifactStore` port: streaming puts, checksum verification, atomic
  commit (blob before manifest), legal hold, and repair support.
- Database rows reference committed artifact hashes; an outbox/transactional
  finalization pattern and a `repair` command reconcile orphaned rows/objects.

## Consequence

Local-first by default; team deployment is a config change, not a code fork.
