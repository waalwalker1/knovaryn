# Concepts — Dataset Provenance and Lineage

**Dataset provenance** is the property that every training example can be
resolved, hop by hop, to the exact permitted source evidence that supports it.
Knovaryn persists that chain as real records — it is enforceable, not a display
string. This page is the SEO / orientation summary; the full canonical chain is
in [Provenance and the Canonical Data Model](provenance.md).

## The chain

```
SourceDocument
   └─(Docling)─────▶ ParsedDocument
        └─spans────▶ SourceSpan (page, section, element, char range, quoted text)
             └─group▶ Chunk (structure-aware: heading path, table/list, tokens)
                  └─▶ GenerationCandidate (per topology)
                       └─▶ TrainingExample (evidence refs + content hash)
                            └─(accepted)──▶ DatasetVersion
                                 └─(export)─▶ trainer artifacts
```

Each hop is a persisted entity with stable identifiers, so you can walk an
exported example backward through `SourceSpan → ParsedDocument → SourceDocument`
to the original page and section.

## Guarantees enforced at export

The export **provenance gate** (fail closed) verifies, for every exported row:

- every `source_document_id` resolves to an existing `SourceDocument` in the
  **same project**;
- every `source_span_id` resolves to a `SourceSpan` whose owning document is
  listed by the example;
- every generation-candidate reference resolves;
- the recomputed `content_hash` matches the stored hash.

Any failure **blocks the export** — Knovaryn never returns a successful export
for a row it cannot resolve to evidence.

## Why it matters

Traceable training data means an audit can answer "where did this example come
from?" with a pointer to the original document, page, and sentence — which is
the difference between data you can defend and data you cannot.

## Related

- Deep dive — [Provenance and the Canonical Data Model](provenance.md).
- Guides — [PDF → SFT dataset](../guides/pdf-to-sft-dataset.md), [grounded QA datasets](../guides/grounded-qa-dataset-from-documents.md).
- Export guarantee — [quality gates](quality-gates.md), [release bundles](../reference/exporters.md).
