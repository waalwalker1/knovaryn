# Knovaryn — Proposal: Sample Public Dataset Release

**Document status:** DRAFT proposal for a future public dataset release — produced from **redistributable public-domain / permissive** sources only. Nothing here is claimed to be free of bias, hallucination, or error, and no downstream model-improvement guarantee is implied. Publishing the dataset requires passing the relevant parts of `release-gate.md` (§8 dataset-card/license review, §7 signed artifacts/SBOMs) and legal review.

**Goal:** Ship one small, fully-traceable, quality-gated dataset that proves the pipeline and gives the community something to inspect — every example carrying evidence spans and lineage to a *publicly viewable* source.

---

## 1. Objectives

1. Demonstrate the full loop on a **redistributable** corpus.
2. Give reviewers a concrete artifact to audit (evidence, reason codes, dataset cards).
3. Sanity-check the quality heuristics against real public-domain material.
4. Provide a free, small (few-thousand-example) starter for people evaluating Knovaryn.

## 2. Corpus selection criteria

- **Rights:** every source must be public-domain or explicitly permissive (e.g., CC0, CC-BY, US federal works, MIT/Apache/Unlicense text, or clearly self-hosted license-verified text). No copyrighted third-party content without verification.
- **Structure:** prefer sources with tables and headings (procedures, reference material, comparisons) so structure-aware chunking and table preservation are exercised.
- **Verifiability:** sources should be reachable publicly (URLs) so lineage can be checked by anyone.
- **Size:** bounded (e.g., 200–1500 pages) so the release stays cheap and reproducible.

Candidate corpus families (shortlist — final selection listed in §6):
- **Public-domain operations/repair manuals** (e.g., US Army/Navy field manuals published as public domain).
- **CC0/CC-BY reference datasets** already distributed as text.
- **Open-licensed documentation sets** (permissively licensed API/reference docs with consistent structure).

> Note: Knovaryn is not a copyright office. Even for "public domain" material, records must include how each source's status was verified. That evidence is part of the release.

## 3. What the release contains

- **The dataset:** one canonical version with SFT and preference topologies, split train/validation/test, exported to canonical JSONL, Parquet, TRL conversational, and LLaMA-Factory ShareGPT.
- **Evidence per example:** `source_document_ids`, `source_span_ids`, `content_hash`, generation-candidate IDs → publicly resolvable source page/section.
- **Dataset card:** train/val/test counts, source manifest (with license status), license report, privacy report, quality report.
- **Quality report:** acceptance/reject reason-code distribution; quarantined examples excluded.
- **Reproduction bundle:** config files, pinned versions, benchmark methodology (§2.5 sample size, §2.6 errors), and rerun instructions.

## 4. Acceptance targets (provisional — fill with real run)

| Metric | Target (demo size) |
|---|---|
| Total examples | ~2,000 (adjust to corpus) |
| SFT : preference | ~80 : 20 |
| Human-review sample | 5% (**`human_review_sample: 0.05`**), published |
| Accepted-example yield | report actual (no fabricating) |
| Duplicate rate | report actual |
| Quarantined-by-reason | report breakdown (e.g., `grounding<0.9`) |

These are *targets for planning*; the published report states what the actual run produced, including failures.

## 5. Honest-limitations section (in the dataset card)

- Generated with LLM judges/heuristics; **not** guaranteed bias-free, hallucination-free, or error-free.
- Quality thresholds are a configured policy, not objective truth.
- No claim that training on this dataset improves any model; it is a *demonstration and starter*, not a high-performance task set.
- License verification is documented but is not a substitute for independent legal review.

## 6. Go/no-go checklist before publishing

- [ ] Final corpus chosen; every source's redistribution rights verified + documented (URLs + dates).
- [ ] Legal review done for the corpus and the release.
- [ ] Reproducible run completed; numbers recorded honestly (§4 tables filled from real runs).
- [ ] Dataset cards complete; evidence resolvable by a third party.
- [ ] Publish under an open license compatible with source rights (e.g., the *dataset* under a permissive license, distinct from the Apache-2.0 code license) — record per-artifact licensing distinctly.
- [ ] Signed artifacts + SBOMs for the release (release-gate §7).
- [ ] Update `peer-comparison.md` / `media-factsheet.md` with the actual dataset link and numbers.
- [ ] Announce with the factsheet boilerplate (no bias-free/improvement claims).
