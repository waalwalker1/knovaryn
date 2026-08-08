# Concepts — Provenance and the Canonical Data Model

Provenance is the reason Knovaryn exists. Every accepted training example can
be walked backward, hop by hop, to the exact page and section of a permitted
source document. This page defines the canonical chain and the fields that make
it enforceable.

## The provenance chain

```
SourceDocument
   └─(parsed by Docling)──▶ ParsedDocument
        └─spans──────────▶ SourceSpan (page, section, element, char range, quoted text)
             └─grouped───▶ Chunk (structure-aware: heading path, table/list, tokens)
                  └─fed──▶ GenerationCandidate (per topology)
                       └─▶ TrainingExample (evidence refs + content hash)
                            └─(accepted)──▶ DatasetVersion
                                 └─(export)─▶ trainer artifacts

Example → candidate → chunk → parsed doc → source doc → original page/section
```

Each hop is persisted as its own entity with stable identifiers, so the chain
is *walkable* and *verifiable*, not decorative.

## Entities and the evidence contract

- **SourceDocument** — the permitted original. Records `sha256`, `byte_size`,
  `media_type`, `source_kind` (`upload | local_path | url | repository |
  dataset`), `source_locator_redacted`, `declared_license` /
  `detected_license`, `license_status` (`allowed | review | blocked |
  unknown`), `privacy_classification`, `group_key` (for source-group splits),
  and `intake_status`.
- **ParsedDocument** — one parsing pass, keyed to its source. Records the
  parser name/version, a `parser_config_hash`, and artifact IDs: canonical
  Docling JSON, derived markdown/text, and diagnostics. Explicitly does **not**
  claim error-free extraction.
- **SourceSpan** — a precise slice: `page_number`, `section_path`,
  `element_reference`, `character_start`/`end`, bounding boxes, and
  `quoted_text` with its own `sha256`. This is the unit of evidence.
- **Chunk** — a structure-aware grouping of spans: `heading_path`,
  `page_start`/`end`, `structural_type` (`text | table | list | ...`),
  `token_count`, `rendered_context`, `source_span_ids`, and chunker
  name/version/config hash. Tables and lists stay together by default.
- **GenerationCandidate** — the raw generator output before validation, typed
  per topology (SFT, preference, KTO, evaluation) with its own `evidence` refs.
- **TrainingExample** — the validated, canonical row. Carries
  `source_document_ids`, `source_span_ids`, `generation_candidate_ids`,
  `content_hash`, `quality_status`, `quality_score`, `quality_dimensions`,
  `defect_taxonomy`, split assignment, `trainer_visible_metadata`, and
  `private_audit_metadata` (kept out of public exports unless enabled).
- **DatasetVersion** — a frozen snapshot with semantic version, parent link,
  and artifact IDs for the manifest, quality report, dataset card, source
  manifest, license report, and privacy report.

## External handles

Externally visible handles are **UUIDv7** (sortable, cryptographically strong);
sequential database IDs are never exposed. Handles are namespaced with a prefix
(`job_…`, `project_…`, `example_…`). Raw secrets (leases, confirmations) use
cryptographic random tokens, never sequential or guessable values.

## The provenance minimum (enforced)

An exportable example must satisfy a *provenance minimum* — the policy checks
that the following are non-empty and reviewable:

- `source_document_ids`
- `source_span_ids` (when `quality.require_evidence` is true, the default)
- `content_hash`
- `generation_candidate_ids`
- a `quality_status` that is `accepted` or `review`

If any of these are missing, the example is **not exportable**, regardless of
its quality score. This is a gate in the domain policy, not a convention.

## `knovaryn://` and content integrity

Resources are addressable as `knovaryn://` URIs (e.g.
`knovaryn://projects/{id}/...`). Content is integrity-protected: rows reference
committed artifact hashes, artifacts are written blob-before-manifest so a
crash never leaves a dangling reference, and a `repair` command reconciles
orphaned rows/objects.

## Splits respect source groups

Split assignment uses **grouped random** by default on `group_key` (e.g. by
source document), so a document does not leak fragments across train and
validation/test. The split (`train/validation/test`, default `80/10/10`, `seed`
42) is part of the plan and recorded per example.
