# Concepts — Quality, Acceptance, and Quarantine

Knovaryn's job is to make the quality judgment *visible and accountable*, not to
pretend it can certify data. This page describes the quality dimensions, the
acceptance policy, quarantine, and human review.

> **Honest framing:** quality is measured relative to a configurable policy and
> your corpus. A passing example is one that met the policy's floors — it is
> **not** a guarantee of correctness, and a dataset that passes gating is
> **not** a guarantee of model improvement.

## Quality dimensions

Candidates are scored across named dimensions. The defaults (from the
`balanced-v1` policy) target:

- **grounding** — how directly the content is supported by source evidence
  (floor `0.90`).
- **instruction_fulfillment** — whether the response does what the instruction
  asked (floor `0.80`).
- **preference_signal** — for preference pairs, how clearly the chosen response
  is meaningfully better than the rejected one (floor `0.70`).
- **artifact_resistance** — how little the pair can be separated by superficial
  formatting/refusal cues (floor `0.75`).
- **overall** — the weighted composite floor (`0.82`).

Dimensions produce **reason codes** (e.g. `grounding<0.9`,
`instruction_fulfillment<0.8`) so the *why* is machine-readable and reviewable.
Each assessment also records a concise rationale and the validator/version and
policy version that produced it.

## Acceptance policy

The default `AcceptancePolicy` (spec §14.3) is:

| Floor | Value |
|---|---|
| minimum_overall | 0.82 |
| minimum_grounding | 0.90 |
| minimum_instruction_fulfillment | 0.80 |
| minimum_preference_signal | 0.70 |
| minimum_artifact_resistance | 0.75 |

A candidate is **accepted** only if it clears every applicable floor. In
addition, the domain policy rejects on **high-confidence PII** and **blocked
licenses** by default, and requires the provenance minimum described in
[provenance.md](provenance.md).

All floors are configurable under `quality.*`, and `judge_disagreement` controls
what happens when multiple judges disagree (default `review`, meaning the
disagreement routes to human review rather than being auto-accepted).

## Quarantine

Examples that do **not** meet the policy are **quarantined with a reason**, not
silently dropped or, worse, included. Quarantined rows:

- carry a `quality_status` of `rejected` (or `blocked`);
- are excluded from every export path;
- are listed with their reason codes by the validation/preview surfaces
  (REST, MCP `knovaryn_validate_dataset` / `knovaryn_preview_examples`).

This is the difference between "we generated N examples" and "N-k examples met
the policy, and here is why the other k did not." Quarantine is a *policy
decision*, not a claim that a rejected example is provably wrong.

## Human review

Examples that need a human (initially `review` status, judge disagreement, or
any policy-configured sample fraction — default `0.05`) are surfaced through
the REST API / MCP preview tools with their evidence attached; the CLI records
the decision as an immutable revision:

```bash
knovaryn review <ex_handle> approve --reviewer alice --note "grounded"
knovaryn review <ex_handle> reject  --reviewer alice --note "grounding<0.9"
```

A reviewer sees the example plus its evidence block
(`source_document_ids`, `source_span_ids`, content hash) and the recorded
reason, then accepts or rejects. Because every row carries its evidence and
reason codes, human review is about judgment on an *informed* row, not
re-verifying provenance from scratch.

## What quality is NOT

- Not a guarantee of absence of bias or hallucination.
- Not a guarantee that accepted examples improve any model.
- Not legal clearance (licensing is separate — see
  [privacy-licensing](../security/privacy-licensing.md)).
- Benchmarks and the acceptance policy are documented and reproducible, but the
  floors are policy choices — adjust them to your corpus and stakes.
