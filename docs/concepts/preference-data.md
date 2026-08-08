# Concepts — Preference Data (DPO / KTO)

Preference (DPO-style) data is harder to generate well than SFT data, and its
failure modes are different: pairs that are trivially separable, pairs where the
"rejected" response is a formatting giveaway rather than a content mistake, or
pairs that encode hidden reasoning that leaks. This page documents how Knovaryn
constructs preference pairs and what it guards against.

## Topology

Knovaryn plans **preference** topologies to produce a prompt plus a **chosen**
and a **rejected** assistant response. The generator emits a
`GeneratedPreferenceCandidate` carrying:

- `prompt_messages`, `chosen_messages`, `rejected_messages`;
- an `evidence` block pointing at source spans;
- a `rejected_defect` from a fixed taxonomy;
- an `expected_preference_margin` (`small | medium | large`).

The rejected response is **not** picked at random or faked with a weak model —
it is produced by a *controlled negative strategy* so the defect is meaningful.

## Controlled negatives (negative_strategy)

The default strategy is `edit_chosen_near_miss`: start from the correct (chosen)
answer grounded in evidence and introduce a targeted, evidence-aware defect to
create the rejected variant. The defect is classified by the taxonomy:

- `subtle_factual_error`
- `unsupported_inference`
- `instruction_omission`
- `reasoning_error`
- `citation_mismatch`
- `format_violation`
- `unhelpful_refusal`
- `unsafe_compliance`
- `irrelevant_detail`

Recording `rejected_defect` matters for downstream analysis: you can audit what
*kind* of preference signal a dataset actually teaches.

## Length band (length_ratio_min / max)

By default chosen/rejected responses must fall inside a **length-ratio band**
(`0.80`–`1.25`). If the chosen answer is far longer, a model could exploit
length as a proxy instead of learning content preference. `check_length_band`
computes `approximate_tokens(chosen) / approximate_tokens(rejected)` and rejects
pairs outside the band.

## Artifact separability

Knovaryn estimates whether a pair is **trivially separable** by superficial
features — token count, bullets, headings, refusal phrases, citation markers,
punctuation, and differing format — via `preference_is_trivially_separable`.
A pair whose chosen/rejected sides are separable mostly by these features is a
weak learning signal and is rejected or routed to review (floor
`artifact_resistance` 0.75). The point is to force the signal to live in
*content*, not formatting.

## No hidden chain-of-thought

Knovaryn deliberately does **not** generate responses that reveal a
chain-of-thought in the assistant message. The generated note and any reasoning
stays in private/audit metadata; the trainer-visible assistant text is a direct
answer grounded in evidence, so the exported dataset does not teach hidden
reasoning leakage.

## Limitations (be honest)

- Preference quality is **heuristic**. The length band and artifact separator
  reduce easy exploits; they do not guarantee the chosen response is actually
  better in a way a real reward model will recover.
- Controlled negatives are generated from evidence, but the generator can still
  make the "negative" *too* easy or *too* subtle. `expected_preference_margin`
  and `judge_disagreement` (default `review`) exist precisely because these
  judgments are fallible.
- A dataset of preference pairs, however careful, does not guarantee DPO/KTO
  training will improve the target model.
- `preference_signal` is scored by a judge against the policy floor, but that
  score is relative to the policy and corpus, not an absolute truth.
