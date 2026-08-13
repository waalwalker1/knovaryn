# Guide — Build DPO preference data

This guide builds a **DPO/preference dataset** with Knovaryn: generate
`(prompt, chosen, rejected)` triples that are grounded in permitted source
documents, control the quality of the rejected response, gate them, and export
a trainer-ready **TRL preference** (or KTO) dataset.

> **What makes this hard:** preference pairs that are trivially separable, or
> where "rejected" is a formatting giveaway, teach the model nothing. Knovaryn
> produces rejected responses with a *controlled negative strategy* and records
> the defect, so pairs are meaningful and auditable.

## Prerequisites

- Knovaryn installed — see the [quickstart](quickstart.md).
- Permitted sources — see [license and privacy](../concepts/license-and-privacy.md).
- See [PDF → SFT dataset](pdf-to-sft-dataset.md) for the shared intake steps.

## 1. Create a project and add sources

Drive the MCP tools (or REST/SDK):

1. **`knovaryn_create_project`** — a project for the preference dataset.
2. **`knovaryn_add_source`** — add permitted documents with declared licenses.
3. **`knovaryn_license_report`** — confirm the rights are recorded.

## 2. Plan the preference topology

Call **`knovaryn_estimate_run`** with a **preference** generation topology to
review the dry-run cost estimate first.

> The planner produces preference topologies as `(prompt, chosen, rejected)`
> where the **chosen** answer is grounded in evidence and the **rejected**
> answer is created by a controlled negative strategy (default
> `edit_chosen_near_miss`), with the defect classified from a fixed taxonomy
> (e.g. `subtle_factual_error`, `unsupported_inference`), and an
> `expected_preference_margin` when available. See
> [preference data](../concepts/preference-data.md).

## 3. Start the pipeline

Call **`knovaryn_start_pipeline`** with the preference topology, then track with
**`knovaryn_get_job`** / **`knovaryn_list_jobs`** (durable, resumable).

## 4. Review pairs, not just rows

Call **`knovaryn_preview_examples`** to inspect pairs and their defect labels,
then **`knovaryn_review_example`** to accept or reject. A review creates a new
immutable revision with the decision persisted — later reviews cannot silently
rewrite earlier ones.

## 5. Validate and gate

Call **`knovaryn_validate_dataset`**. The
[quality gate](../concepts/quality-gates.md) checks the preference-specific
invariants (chosen/rejected distinctness, rejection reason present, formatting
not a giveaway, grounding of the chosen response). Failures are quarantined.

## 6. Export TRL preference (or KTO) data

Call **`knovaryn_create_dataset_version`**, then
**`knovaryn_export_dataset`** with `format=trl_preference` for framework-native
DPO data, or `format=kto` for KTO. Every exported row keeps its source evidence
references and content hash, and the release bundle ships with a detached
checksum + per-file manifest.

> Same inputs, different target: KTO data from the same pipeline is exported
> with `format=kto`. See the [exporter reference](../reference/exporters.md).

## Related

- Concepts — [preference data](../concepts/preference-data.md), [quality gates](../concepts/quality-gates.md).
- Guides — [Hugging Face export](hugging-face-export.md), [grounded QA datasets](grounded-qa-dataset-from-documents.md).
