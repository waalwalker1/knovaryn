# Security — Hardening Checklist

Use this checklist when deploying Knovaryn to anything beyond a throwaway
local demo. The architecture rationale is in
[architecture/security.md](../architecture/security.md). Work through these
before relying on Knovaryn in a shared or regulated environment.

> These are engineering controls and reduce risk; they are not a certification
> and do not make licensing or privacy compliance automatic.

## Network exposure

- [ ] Keep the local control plane bound to loopback (`127.0.0.1:8765`) and
      terminate TLS + authentication at a reverse proxy if you expose it at all.
- [ ] Keep **URL ingestion off** (`sources.url_ingestion: false`) unless you
      have a use case; if enabled, confirm SSRF protections (host allow/deny,
      redirects, loopback/link-local rejection, timeouts) before use.
- [ ] Do not expose PostgreSQL or MinIO directly to untrusted networks.

## Source intake

- [ ] Configure `sources.allowed_roots` to the smallest set you need.
- [ ] Keep `sources.follow_symlinks: false`.
- [ ] Set `sources.max_file_mb` and `sources.max_pages` to bound resource use.
- [ ] Treat every source document as **untrusted** (spec §8.6): block or
      review unknown/blocked licenses, and act on high-confidence PII.

## Authentication / authorization (team deployments)

- [ ] Enforce **least-privilege resource scopes** (`projects:read`,
      `sources:write`, `runs:execute`, `datasets:publish`, …) per principal.
- [ ] Set admin policy for protected keys (`sources.url_ingestion`,
      `storage.database_url`) so project config cannot weaken them.
- [ ] Confirm remote handles are bound to the authenticated owner and are
      unguessable (UUIDv7) — never reuse sequential IDs.

## Secrets

- [ ] Never pass provider API keys through MCP tool arguments or client config
      JSON. Set them in the server process environment.
- [ ] Keep `telemetry.content_in_logs: false` and verify content is not written
      to logs.
- [ ] Confirm `source_locator_redacted` (not raw paths/credentials) is what is
      stored. Confirm provider keys are redacted from audit/telemetry.

## No shell

- [ ] Confirm no MCP tool, REST endpoint, or CLI verb executes arbitrary shell
      commands. If you are extending Knovaryn, do not add a shell surface.

## Privacy and retention

- [ ] Review `privacy.detect_pii`, `privacy.high_confidence_pii_action`
      (`quarantine`), `provider_data_allowed`, and `store_raw_prompts` against
      what your policy requires.
- [ ] Set `privacy.retention_days` to your retention obligation.

## Supply chain and CI

- [ ] Confirm CI runs dependency, container, secret, and static-analysis scans,
      and that no critical/high unaccepted vulnerability ships.
- [ ] Install heavy extras (`docling`, `docetl`, `litellm`, `s3`, `parquet`,
      `hub`, `ml`) only when needed, to reduce the default attack surface.
- [ ] Prefer pinned, reproducible dependency versions (`uv.lock`).

## Operations

- [ ] Run `knovaryn doctor` in the deployed environment and confirm storage,
      profile, and provider wiring before real jobs.
- [ ] Use `knovaryn dataset publish`'s `dry_run` + confirmation token flow, and
      review the license/privacy reports before any public publish.
- [ ] Set a sane `budget.maximum_cost_usd` and monitor `actual_cost` on
      billable runs.
- [ ] Have a plan to run `repair` to reconcile orphaned rows/objects after a
      crash, per the storage design.
