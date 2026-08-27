---
description: >-
  License- and privacy-aware curation: declared-source licenses,
  privacy classifications, and redaction before anything enters a
  generation run.
---

# Concepts — License- and Privacy-Aware Dataset Curation

Knovaryn is designed for **license-aware** and **privacy-aware** training-data
curation: it tracks the rights on your sources, flags sensitive content, and
**refuses to publish** anything it cannot show is permitted. This page is the
orientation summary; the operational checklist is in
[Privacy & Licensing](../security/privacy-licensing.md).

## License awareness

- Every source document carries a **declared license** in the source-license
  registry.
- The **license gate** blocks any sample whose sources are not permitted to be
  used for training.
- **Publication is dry-run by default** and gated on license approval — nothing
  is pushed anywhere without explicit authorization.
- Code licensing (Apache-2.0) is kept separate from dataset licensing; dataset
  licensing is governed by the source-license registry.

## Privacy awareness

- **Untrusted-in, controlled-out:** every source is treated as untrusted at
  intake; nothing in a source can drive code execution, path traversal, or
  prompt injection.
- **Secrets from the environment only** — never hard-coded, never logged,
  redacted at the display boundary.
- Server-side privacy reports classify sensitive content per policy; the
  privacy gate flags failures rather than exporting them.
- **Local by default:** SQLite + filesystem; scale to a team deployment
  (PostgreSQL + S3-compatible) is a config change, not a fork.

## When you move to production

The built-in controls **reduce risk; they are not a certification**. Whether a
given corpus may be used for training is a legal determination you make for your
jurisdiction, your contract terms, and the provenance of each document. See
[Privacy & Licensing](../security/privacy-licensing.md) and the
[deployment guide](../deployment/profiles.md).

## Related

- Deep dive — [Privacy & Licensing](../security/privacy-licensing.md), [hardening](../security/hardening.md).
- Concepts — [quality gates](quality-gates.md), [dataset provenance](dataset-provenance.md).
- Security model — [architecture/security](../architecture/security.md).
