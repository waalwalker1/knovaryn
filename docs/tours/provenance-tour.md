---
description: >-
  Follow one exported example back through its lineage —
  candidate, chunk, source span, parsed document, original file —
  in this guided provenance tour.
---

# Tour — Follow one example back to its source

This page walks the provenance chain on **real output from the offline demo**
(`knovaryn demo`): a deterministic, synthetic run on two bundled sample
documents with the fake provider — no network, no keys, no external model.
Every identifier, hash, quote, and quality result below is copied from that
run. **The content itself is synthetic demo text** ("MLOps Lifecycle",
"Incident response runbook") — it exists to demonstrate mechanics, not to
teach MLOps.

The run produced 10 candidates from 10 chunks: **3 accepted, 6 rejected, 1
held for review**. Select a row to see everything Knovaryn recorded about it:

<div class="kn-tabs">
  <input type="radio" name="kn-tour-row" id="kn-row-0" checked>
  <label for="kn-row-0"><span class="kn-state kn-state--accepted">Accepted</span> SFT example</label>
  <input type="radio" name="kn-tour-row" id="kn-row-1">
  <label for="kn-row-1"><span class="kn-state kn-state--rejected">Rejected</span> SFT example</label>
  <input type="radio" name="kn-tour-row" id="kn-row-2">
  <label for="kn-row-2"><span class="kn-state kn-state--review">Review</span> preference pair</label>

  <div class="kn-tabpanels">

    <section class="kn-panel">
      <h3>An accepted example, fully traced</h3>
      <div class="kn-evidence">
        <div class="kn-metric"><div class="kn-metric__label">Prompt (user message)</div><div class="kn-metric__value" style="font-size:0.85rem">"Based only on the provided material, summarize the key point about: MLOps Lifecycle"</div></div>
        <div class="kn-metric"><div class="kn-metric__label">Answer (assistant message)</div><div class="kn-metric__value" style="font-size:0.85rem">"According to the provided material: MLOps Lifecycle MLOps Lifecycle"</div></div>
        <div class="kn-metric"><div class="kn-metric__label">Source document</div><div class="kn-metric__value" style="font-size:0.85rem">"MLOps lifecycle overview" — <code>text/markdown</code>, 957 bytes</div></div>
        <div class="kn-metric"><div class="kn-metric__label">Source quote (the span)</div><div class="kn-metric__value" style="font-size:0.85rem">"MLOps Lifecycle"</div></div>
        <div class="kn-metric"><div class="kn-metric__label">Location precision</div><div class="kn-metric__value"><code>section</code> — chars 0–15, section path <code>MLOps Lifecycle</code></div></div>
        <div class="kn-metric"><div class="kn-metric__label">Page / bounding box</div><div class="kn-metric__value">Not available — markdown has no pages. A Docling-parsed PDF records page number and bounding box; this source honestly records <code>section</code> precision.</div></div>
        <div class="kn-metric"><div class="kn-metric__label">Content hash</div><div class="kn-metric__value" style="font-size:0.75rem; word-break:break-all"><code>085f04348bb5a3b4c7f45fb5a30ca3674d64319d741d3b32484a5df2e2027f1e</code></div></div>
        <div class="kn-metric"><div class="kn-metric__label">Quality result</div><div class="kn-metric__value"><span class="kn-state kn-state--accepted">accepted</span> score 1.0 — all deterministic dimensions verified</div></div>
        <div class="kn-metric"><div class="kn-metric__label">Review state</div><div class="kn-metric__value">No human review required (auto-accepted under demo policy floors)</div></div>
        <div class="kn-metric"><div class="kn-metric__label">Dataset version</div><div class="kn-metric__value"><code>0.1.0</code> — immutable snapshot, content-hash of all members</div></div>
        <div class="kn-metric"><div class="kn-metric__label">Export format</div><div class="kn-metric__value">OpenAI-chat JSONL at <code>data/validation.jsonl</code> inside <code>release.zip</code>, with detached checksums + manifest</div></div>
      </div>
      <p>The full walk for this row, hop by hop:</p>
      <table>
        <thead><tr><th>Chain hop</th><th>Record (from the run)</th></tr></thead>
        <tbody>
          <tr><td>Exported example</td><td><code>ex_01a03d42-29ab-7b0f-9c3d-a45cac20c1c1</code> — carries <code>source_span_ids</code>, <code>source_document_ids</code>, <code>generation_candidate_ids</code>, <code>content_hash</code></td></tr>
          <tr><td>Generation candidate</td><td><code>cand_01a03d42-29a1-755b-863d-e02a7dcd176d</code> — task family <code>factual_explanation</code>, topology <code>sft</code>, status <code>accepted</code></td></tr>
          <tr><td>Chunk</td><td><code>ck_7f68289ce0b8faeb2d231e81</code> — heading path <code>MLOps Lifecycle</code>, ordinal 0, chunker <code>structure_aware</code>, <code>sha256 fb19b9f2…9f37</code></td></tr>
          <tr><td>Source span</td><td><code>sp_7f68289ce0b8faeb2d231e81</code> — quotes "MLOps Lifecycle", characters 0–15, precision <code>section</code>, same <code>sha256</code> as the chunk text</td></tr>
          <tr><td>Parsed document</td><td><code>par_01a03d42-298a-725d-955e-5b04a3f96948</code> — parser <code>fallback-text</code> v1, config hash <code>demo</code>, extraction status <code>parsed</code></td></tr>
          <tr><td>Source document</td><td><code>src_01a03d42-2986-7e13-a70f-4423c932cb06</code> — 957 bytes, group key <code>MLOps lifecycle overview</code>, license/privacy recorded at intake</td></tr>
        </tbody>
      </table>
    </section>

    <section class="kn-panel">
      <h3>A rejected example — quarantined with its reasons</h3>
      <div class="kn-evidence">
        <div class="kn-metric"><div class="kn-metric__label">Prompt (user message)</div><div class="kn-metric__value" style="font-size:0.85rem">"Based only on the provided material, summarize the key point about: Data preparation<br>Data preparation is the first step of any machine learning project."</div></div>
        <div class="kn-metric"><div class="kn-metric__label">Answer (assistant message)</div><div class="kn-metric__value" style="font-size:0.85rem">"According to the provided material: Data preparation<br>Data preparation is the first step of any machine learning project. It involves collecting raw data, cleaning it, and transforming it into a usable format."</div></div>
        <div class="kn-metric"><div class="kn-metric__label">Source quote (the span)</div><div class="kn-metric__value" style="font-size:0.8rem">"Data preparation<br>Data preparation is the first step of any machine learning project. It involves collecting raw data, cleaning it, and transforming it into a usable format. Practitioners must document the provenance of every data source to keep the dataset auditable."</div></div>
        <div class="kn-metric"><div class="kn-metric__label">Location precision</div><div class="kn-metric__value"><code>section</code> — chars 0–267, section path <code>MLOps Lifecycle/Data preparation</code></div></div>
        <div class="kn-metric"><div class="kn-metric__label">Page / bounding box</div><div class="kn-metric__value">Not available — markdown source; <code>section</code> precision is recorded honestly</div></div>
        <div class="kn-metric"><div class="kn-metric__label">Content hash</div><div class="kn-metric__value" style="font-size:0.75rem; word-break:break-all"><code>108468b395092ad4cac21ec28338edadf1e943e3f80040852dcfe8ff7115ae7f</code></div></div>
        <div class="kn-metric"><div class="kn-metric__label">Quality result</div><div class="kn-metric__value"><span class="kn-state kn-state--rejected">rejected</span> score 0.89 — <code>subject_object_reversal</code>, <code>critical_failed:semantic_consistency</code></div></div>
        <div class="kn-metric"><div class="kn-metric__label">Review state</div><div class="kn-metric__value">Quarantined — never exported, reason codes kept for audit</div></div>
        <div class="kn-metric"><div class="kn-metric__label">Dataset version / export</div><div class="kn-metric__value">Not a member of version <code>0.1.0</code> — absent from <code>release.zip</code> by construction</div></div>
      </div>
      <p><strong>What the gate caught:</strong> the answer reorders the source's
      subject and object ("collecting raw data" becomes the project's
      definition rather than its first step). The deterministic
      semantic-consistency check flags the reversal as
      <code>subject_object_reversal</code>, it is a critical dimension, and a
      critical failure is a hard reject — the row is quarantined with its
      reason codes and never reaches the export.</p>
    </section>

    <section class="kn-panel">
      <h3>A preference pair held for human review</h3>
      <div class="kn-evidence">
        <div class="kn-metric"><div class="kn-metric__label">Prompt (user message)</div><div class="kn-metric__value" style="font-size:0.85rem">"Based only on the provided material, summarize the key point about: MLOps Lifecycle"</div></div>
        <div class="kn-metric"><div class="kn-metric__label">Chosen answer</div><div class="kn-metric__value" style="font-size:0.85rem">"According to the provided material: MLOps Lifecycle MLOps Lifecycle"</div></div>
        <div class="kn-metric"><div class="kn-metric__label">Rejected answer</div><div class="kn-metric__value" style="font-size:0.85rem">"According to the provided material: MLOps Lifecycle MLOps Lifecycle (this additional claim was not supported)."</div></div>
        <div class="kn-metric"><div class="kn-metric__label">Source quote (the span)</div><div class="kn-metric__value" style="font-size:0.85rem">"MLOps Lifecycle" — same span as the accepted row above</div></div>
        <div class="kn-metric"><div class="kn-metric__label">Location precision</div><div class="kn-metric__value"><code>section</code> — chars 0–15</div></div>
        <div class="kn-metric"><div class="kn-metric__label">Page / bounding box</div><div class="kn-metric__value">Not available — markdown source</div></div>
        <div class="kn-metric"><div class="kn-metric__label">Content hash</div><div class="kn-metric__value" style="font-size:0.75rem; word-break:break-all"><code>51db07d68f0840795ebdf7a6bc0cc6cb1a2cfb3a8471ac87907e4617262d8ae9</code></div></div>
        <div class="kn-metric"><div class="kn-metric__label">Quality result</div><div class="kn-metric__value"><span class="kn-state kn-state--review">review</span> score 0.85 — <code>length_band_violation</code>, <code>trivial_separation</code>, <code>preference_signal&lt;0.7</code>, <code>artifact_resistance&lt;0.75</code></div></div>
        <div class="kn-metric"><div class="kn-metric__label">Review state</div><div class="kn-metric__value">Waiting in the review queue — a human approves or rejects with <code>knovaryn review</code> (immutable revisions, evidence attached)</div></div>
        <div class="kn-metric"><div class="kn-metric__label">Dataset version / export</div><div class="kn-metric__value">Not exported while unreviewed — preference pairs ship only after a decision</div></div>
      </div>
      <p><strong>Why review, not reject?</strong> The pair's separation is weak
      (the chosen and rejected answers differ by one appended sentence), so the
      deterministic preference-signal check scores it below the floor. That is
      a judgment call a human should make, so the pair is routed to review
      instead of silently shipping or silently vanishing.</p>
    </section>

  </div>
</div>

## Reading the chain

- **Every hop is a persisted record with a stable ID** — the walk above is a
  real query path, not a narrative: the `knovaryn_lineage` MCP tool, the
  `GET /v1/projects/{id}/examples/{id}/lineage` REST endpoint, and the web
  console's lineage view all traverse it.
- **The span quotes its text and hashes it.** Grounding is checkable: the
  validator scores the answer against the quoted span only.
- **Precision is reported, never exaggerated.** A Docling-parsed PDF yields
  page numbers and bounding boxes; a markdown file honestly yields
  `section` precision and no bounding box. The demo uses the fallback text
  parser because the Docling extra is not installed in a bare
  `pip install knovaryn` — the parsed-document record says so explicitly.
- **Quarantine is a first-class outcome.** Rejected rows keep their reason
  codes and lineage; they just never enter a version.

## Reproduce this tour

```bash
pip install knovaryn
knovaryn demo --examples 6 --json
```

The run is deterministic (fake provider, seeded splits), so your identifiers
will differ (they are time-derived) but the shape, counts, and outcome types
match what you see above. Inspect any row yourself:

```bash
unzip -p knovaryn-demo/release.zip data/validation.jsonl | python3 -m json.tool
```

Related: [provenance concepts](../concepts/provenance.md) ·
[quality-gates tour](quality-gates-tour.md) ·
[CLI reference](../reference/cli.md)
