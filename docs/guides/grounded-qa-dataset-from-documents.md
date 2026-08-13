# Guide — Grounded QA dataset from documents

This guide builds a **grounded question-answer (QA) dataset** from documents:
generate questions and answers that are *grounded* in the source text, gate
them so every answer is supported by persisted evidence, and export them as
evaluation or instruction data.

> **The key guarantee:** an example only exports if its answer can be resolved
> through persisted lineage to evidence in a permitted source document. Ungrounded
> or weakly-supported rows are quarantined, not shipped.

## Prerequisites

- Knovaryn installed — see the [quickstart](quickstart.md).
- Permitted sources — [license and privacy](../concepts/license-and-privacy.md).
- Shared intake steps — [PDF → SFT dataset](pdf-to-sft-dataset.md).

## 1. Create a project and add sources

1. **`knovaryn_create_project`** — project for the QA/evaluation dataset.
2. **`knovaryn_add_source`** — add permitted documents (PDF, Markdown, etc.).
3. **`knovaryn_license_report`** — confirm recorded rights.

## 2. Plan the QA / evaluation topology

Call **`knovaryn_estimate_run`** with an **evaluation** (grounded QA) topology
for a dry-run cost estimate before anything is spent.

> A grounded QA topology generates a `(question, answer)` pair together with an
> `evidence` block pointing at source spans. Generating QA from documents is
> useful both to **evaluate** a model (retrieval-augmented / RAG evaluation
> datasets) and to **fine-tune** it on grounded instruction data.

## 3. Start the pipeline

Call **`knovaryn_start_pipeline`** with the QA/evaluation topology; track with
**`knovaryn_get_job`** / **`knovaryn_list_jobs`**.

## 4. Review and check lineage

Call **`knovaryn_preview_examples`** to inspect Q/A pairs, then
**`knovaryn_lineage`** to walk each example back through chunk → parsed document
→ source document → exact page/section. Use **`knovaryn_review_example`** to
persist an accept/reject decision (as a new immutable revision).

## 5. Validate and gate

Call **`knovaryn_validate_dataset`** — the
[quality gate](../concepts/quality-gates.md) includes a **grounding** validator
that rejects answers not supported by evidence, plus schema, format, refusal,
duplicate, contamination, privacy, and license checks. Failures are quarantined.

## 6. Export

Call **`knovaryn_create_dataset_version`**, then **`knovaryn_export_dataset`**:
- `format=evaluation` for a QA/evaluation layout,
- or any instruction format (`openai_chat`, `trl_sft`, `alpaca`) if you are
  using the QA pairs for fine-tuning.

Every row keeps its `source_document_ids`, `source_span_ids`, and `content_hash`;
the release bundle ships a detached checksum + per-file manifest.

## RAG evaluation notes

For **RAG evaluation datasets** generated from documents, the same groundedness
guarantee is what makes the evaluation trustworthy: if a question cannot be
answered from the provided evidence, that is either quarantined or surfaced as a
policy decision — it is never silently exported as if it were answerable.

## Related

- Concepts — [dataset provenance](../concepts/dataset-provenance.md), [quality gates](../concepts/quality-gates.md).
- Guides — [Hugging Face export](hugging-face-export.md), [build DPO preference data](build-dpo-preference-data.md).
