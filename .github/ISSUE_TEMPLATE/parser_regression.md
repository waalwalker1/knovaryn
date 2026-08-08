---
name: Parser regression
about: Report a parser/normalization regression — a document that no longer parses as expected
title: "[Parser] "
labels: ["parser"]
assignees: ""
---

> A **parser regression** is when a document, or type of document, that previously
> parsed correctly now produces wrong or missing output, or fails. Build-time
> ParseErrors on already-supported inputs can also fit here.

## Document type

<!-- What kind of source document? PDF, DOCX, HTML, Markdown, scanned/image PDF... -->

## Regression summary

<!-- What changed? Since which version/commit did this start? If you know, include
the earlier version that worked. -->

## Expected vs actual

<!-- What structure/content should have come out (headings, tables, paragraphs,
page order)? What actually came out? -->

- **Expected:**
- **Actual:**

## Steps to reproduce

<!-- Minimal reproduction, ideally with a sample document or a redacted version.
If the document cannot be shared, describe its structure precisely. -->

```bash

```

## Source-document safety note

<!-- Knovaryn treats source documents as untrusted data (spec §8.6). Confirm: -->
- [ ] The document is something I am permitted to share/ingest.
- [ ] The document contains no secrets, PII, or proprietary content, or has been
      redacted.

## Relevant output

<!-- Pipe the failing parser/CLI/MCP/REST output here, redacted. -->

```
```

## Diagnostics

- Knovaryn version / commit:
- Parser backend in use (Docling adapter, golden-fallback, optional DocETL):
- Extras installed (`docling`, `docetl`)? :
- Error trace (if a failure):

## Impact

<!-- Does this affect provenance tracing, chunking, or downstream SFT/preference
quality? -->
