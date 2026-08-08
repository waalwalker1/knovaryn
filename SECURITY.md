# Security Policy

## Reporting a vulnerability

Knovaryn takes security seriously. **Please do not open a public issue** for a
security vulnerability.

Report privately to the security maintainers at **`security@knovaryn.dev`**
(or use the private security reporting path once the repository is public, such
as GitHub private vulnerability reporting).

Include:

- the affected version(s) and commit hash if known;
- a minimal reproduction;
- impact assessment (confidentiality/integrity/availability);
- any suggested mitigation.

We aim to acknowledge within 3 business days and to keep you informed as the
fix is prepared.

## Supported versions

| Version | Supported |
|---|---|
| latest | ✅ |
| older releases | ❌ (migrate to latest) |

## Security posture

Knovaryn treats **source documents as untrusted data** (spec §8.6). See
`docs/security/` for the threat model, hardening guide, and security
architecture. Key behaviors:

- remote handles are random, unguessable, and bound to the authenticated owner;
- URL ingestion is disabled by default and SSRF-protected when enabled;
- local HTTP binds to loopback by default with Host/Origin validation;
- no MCP tool accepts a shell command;
- provider keys are never accepted through tool arguments and are redacted;
- dependency, container, secret, and static-analysis scans run in CI;
- no critical/high unaccepted vulnerability ships in a release.

## Public disclosure

After a fix ships, we coordinate public disclosure with the reporter. Credit is
given unless anonymity is requested.
