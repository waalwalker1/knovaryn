# Knovaryn — the Traceability Story, One Page

**The claim:** every training example Knovaryn produces can be walked backward, hop by
hop, to the exact page and section of a permitted source document — and you can verify
that yourself in a one-line install, with no API keys.

**Status:** 0.1.0 (alpha, technical preview). Apache-2.0 · Python ≥ 3.11. Repo:
[github.com/waalwalker1/knovaryn](https://github.com/waalwalker1/knovaryn)

---

## Verify it in 90 seconds

```bash
pip install knovaryn          # lean core — no docling/llm extras required
knovaryn demo --examples 20 --json    # fully offline, deterministic, no keys
```

Inspect the generated release bundle: a **dataset card**, a **source manifest** (every
source's `sha256`, size, media type, license status), per-example records carrying
`source_document_ids`, `source_span_ids`, and a `content_hash`, plus the quality report,
license report, and a release `sha256`. Walk any example's lineage:

```
Example → generation candidate → chunk → parsed document (Docling) → source document
        → original page & section
```

That chain is what makes the dataset *defensible*: every row can be defended to a
reviewer, a client, or a regulator.

## What "traced to its source" means, concretely

Each hop is a persisted entity with stable identifiers — not a decorative label:

| Hop | What is recorded |
|---|---|
| `SourceDocument` | `sha256`, byte size, media type, source kind, **license status** (`allowed / review / blocked / unknown`), privacy class, group key |
| `ParsedDocument` | parser name/version, config hash, canonical Docling JSON + derived text, diagnostics |
| `SourceSpan` | page number, section path, element ref, char range, bounding box, **quoted text with its own `sha256`** |
| `Chunk` | heading path, page range, structural type, tokens, `source_span_ids`, chunker name/version/config hash |
| `GenerationCandidate` | raw generator output, typed per topology (SFT / preference / KTO / evaluation), its own evidence refs |
| `TrainingExample` | `source_document_ids`, `source_span_ids`, `generation_candidate_ids`, `content_hash`, quality status & reason codes, split assignment |
| `DatasetVersion` | frozen snapshot, semantic version, parent link, manifest / quality / license / privacy report artifact IDs |

**The provenance minimum (an enforced gate, not a convention):** an exportable example
must carry `source_document_ids`, `source_span_ids` (when evidence is required — the
default), `content_hash`, `generation_candidate_ids`, and a reviewable quality status. If
any is missing, the example is **not exportable**, regardless of its quality score.

**Split hygiene:** examples are split by source-group (`grouped_random`, 80/10/10, seed
42), so a single document never leaks fragments across train and validation/test.

## Quality is gated, not assumed

Every candidate is scored against a dated policy across grounding (floor 0.90),
instruction fulfillment (0.80), preference signal (0.70), artifact resistance (0.75),
and an overall composite (0.82). Failures produce **machine-readable reason codes**
(e.g. `grounding<0.9`) and are **quarantined with a reason** — never silently included.
Weak rows are excluded from *every* export path, and reviewers see the evidence block
plus the recorded reason. This is the difference between "we generated N examples" and
"N−k met the policy, and here is why the other k did not."

## Honest status — what is disclosed, what is not "guaranteed"

**Verified and reproducible today (all gates run, offline):**
- **48 passing tests**, deterministic, offline (`uv run pytest -m "not live"`)
- **ruff** lint + format clean, **mypy** clean (91 source files, 0 issues)
- **Alembic** upgrade / `check` (no drift) / downgrade reversible
- **mkdocs** builds; **wheel + sdist** build clean and install into a fresh venv
- Offline `demo` runs the full loop with **no API keys**
- Benchmark harness measures **~1,107 examples/s** (offline, framework cost)

**Honestly NOT guaranteed (we don't overclaim):**
- No guarantee of absence of bias or hallucination.
- No guarantee that an accepted dataset improves any model.
- Licensing gating is a safety rail, **not** legal clearance.
- Coverage is a tracked gap: bridge coverage measures **~54%**, below a 70% internal
  target that has not yet been met. All **48 tests pass**; the coverage *number* is the
  open item, not test correctness.

**Not yet proven externally:** no real users yet, no published reproducible benchmark
numbers (the methodology exists), no 1.0 release gate pass. At 0.1.0 this is an *invite
to verify*, not a "stable" release. API and storage are not yet frozen.

---

This one-pager is the pitch; the code and the CI are the proof. Install it, run the
offline demo, open the dataset card, and walk an example back to its source — that is
exactly the verification we're asking the community to perform.
