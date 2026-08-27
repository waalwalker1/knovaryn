---
description: >-
  Security architecture: fail-closed intake preflight of untrusted
  documents, authorization boundaries, audit trails, and release
  integrity checks.
---

# Architecture — Security

Knovaryn handles documents that are treated as **untrusted input** and exposes
a control plane over MCP, CLI, REST, and web. This page summarizes the threat
model and the controls that matter. The operational checklist lives in
[security/hardening.md](../security/hardening.md).

> **Scope note:** these are engineering controls. They reduce risk; they are not
> a security certification and do not make licensing or privacy compliance
> automatic. Do your own review for regulated use.

## Untrusted documents (spec §8.6)

Source documents are treated as untrusted data:

- **Prompt-injection patterns** in source text are detected (e.g.
  "ignore previous instructions", "you are now", `<|im_start|>`) and surfaced
  before content is trusted as evidence.
- **Blocked/unknown licenses** gate public paths (see
  [privacy-licensing](../security/privacy-licensing.md)).
- **High-confidence PII** rejects by default (`privacy.high_confidence_pii_action`).
- Parsing runs in an isolated, resource-guarded adapter; heavy parsers are
  optional extras, and fallbacks degrade explicitly rather than silently.

## SSRF and URL ingestion

- **URL ingestion is disabled by default** (`sources.url_ingestion: false`).
- When enabled, URL fetches are **SSRF-protected**: target validation, host
  allow/deny, redirect handling, loopback/link-local rejection, and timeouts.
  Enable only in a trusted environment.

## Path traversal and file intake

- Sources are scoped to `sources.allowed_roots`; intake never follows symlinks
  by default (`follow_symlinks: false`).
- `source_locator_redacted` is stored, not raw paths or credentials.
- File size and page limits (`max_file_mb`, `max_pages`) bound resource use.

## Handles and tokens

- All externally visible IDs are **UUIDv7** (unguessable, sortable, bound to
  the authenticated owner). Sequential DB IDs are never exposed.
- Leases, confirmation tokens, and secrets use **cryptographic random tokens**.
- Provider API keys are **never accepted through tool arguments** and are
  redacted from logs and audit trails.

## No shell tools

**No MCP tool, REST endpoint, or CLI verb accepts a shell command or executes
arbitrary user-provided code.** The pipeline composes typed adapters; there is
no "run this command" surface. This removes the largest class of control-plane
injection.

## Local HTTP binding

The local server binds to **loopback by default** (`127.0.0.1:8765`) with
**Host/Origin validation**. It is not intended to be exposed directly to a
network; put it behind an authenticated proxy/TLS for remote access.

## Least-privilege scopes and admin policy

- OAuth-style **resource scopes** (`projects:read`, `sources:write`,
  `runs:execute`, `datasets:publish`, …) gate REST and web actions.
- **Admin policy** overrides project config for protected keys
  (`sources.url_ingestion`, `storage.database_url`); project config cannot
  weaken admin-enforced security/retention policy.
- Remote handles are bound to their owner; a handle is not usable to
  impersonate another principal.

## Privacy and telemetry

- `telemetry.content_in_logs` defaults to **false**; content is not written to
  logs unless explicitly enabled.
- `privacy.provider_data_allowed` and `store_raw_prompts` control what leaves
  the machine; `detect_pii` and retention policies apply.
- Audit events are append-only and include the acting principal.

## Supply chain and release

CI runs dependency, container, secret, and static-analysis scans; no
critical/high unaccepted vulnerability ships in a release. Heavy dependencies
(Docling, DocETL, LiteLLM, S3, Parquet, Hub, ML) are opt-in extras (ADR 0001),
reducing the default install's attack surface.

## Relationships

- Threat model assumption "source documents are untrusted": this page +
  [hardening checklist](../security/hardening.md).
- License/privacy gating details: [privacy-licensing](../security/privacy-licensing.md).
- Reporting a vulnerability: see root `SECURITY.md` (GitHub private vulnerability reporting).
