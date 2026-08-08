---
name: New exporter
about: Request a new dataset export target/format for Knovaryn
title: "[Exporter] "
labels: ["exporter"]
assignees: ""
---

## Target format / destination

<!-- What should Knovaryn be able to export to? e.g. parquet, Arrow IPC, JSONL,
Hugging Face Hub dataset, a specific MCP-toolable store, CSV, or a new schema.
Name the format and any canonical spec it follows. -->

## Use case

<!-- Who needs this and for what downstream work — fine-tuning with a specific
framework (e.g. Hugging Face `datasets`, `trl`, PEFT), a tool, a platform? -->

## Expected output shape

<!-- Briefly describe the expected record structure. Confirm provenance must be
preserved: which fields should trace each example back to its source document,
version, and lineage?

Example sketch (adapt as needed):

```json
{
  "prompt": "...",
  "completion": "...",
  "metadata": {
    "source_document_id": "...",
    "source_version": "...",
    "split": "train",
    "quality_score": 0.0,
    "...": "..."
  }
}
```
-->

## Reference / example output

<!-- Paste a small sample of the expected output, or a link to a spec/schema/example
file in another project that produces it. -->

## Compatibility with existing exporters

<!-- Is this a new format that should live alongside existing exporters, a variant
of one, or a replacement? Should it register under the same pipeline
split/version/export path? -->

## Traceability & license requirements

<!-- Confirm (or flag concerns about) whether this target can faithfully carry
provenance and license metadata. -->
- [ ] The target format can retain source tracing fields.
- [ ] Platform/format licensing permits embedding resolved license metadata.
- [ ] No copyrighted source material is embedded without license resolution.

## Acceptance criteria

<!-- What would let you call this done? -->

- [ ] 
