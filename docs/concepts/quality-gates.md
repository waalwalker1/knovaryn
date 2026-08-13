# Concepts — Quality Gates and Fail-Closed Validation

**Quality gates** are the automated checks every generated example must pass
before it can be included in a dataset version or export. Knovaryn's design is
**fail closed**: an example that fails a gate is **quarantined**, never silently
exported. This page is the orientation summary; the scoring model and policy
floors are in [Quality, Acceptance, and Quarantine](quality.md).

## The gates

Acceptance runs a dated policy (`balanced-v1` by default) across named
dimensions, then applies gate validators that quarantine failures:

- **schema** — the example is structurally valid;
- **grounding** — content is supported by source evidence;
- **completeness** / **answerability** — the example does what the task asked;
- **format** — output matches the requested shape;
- **refusal** — the model did not refuse or hedge;
- **duplicate** — no near-duplicate contamination;
- **contamination** — no train/validation/test leakage;
- **privacy** — sensitive content is flagged per policy;
- **license** — sources are permitted.

A passing example **is not a guarantee of correctness** — it met the policy's
floors. Knovaryn makes the judgment visible and accountable rather than
pretending to certify data.

## Review & revisions

Human review is part of the gate: `knovaryn_review_example` records an
approve / reject / needs-work decision *as a new immutable revision* — it never
mutates an example in place. Rejected examples are excluded from new versions
and exports.

## Immutable versions and releases

A dataset **version** is an immutable snapshot (with a parent chain and a
member-example list captured at creation). A later review cannot silently change
what a version contains. Exported **release bundles** ship a dataset card,
quality/source/license/privacy reports, a per-file manifest, and a detached
checksum.

## Related

- Deep dive — [Quality, Acceptance, and Quarantine](quality.md).
- Concepts — [dataset provenance](dataset-provenance.md), [license and privacy](license-and-privacy.md).
- Implementation — [review & revisions](../architecture/overview.md).
