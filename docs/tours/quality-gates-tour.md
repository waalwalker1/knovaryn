---
description: >-
  Watch the quality gates decide: groundedness, schema, and policy
  checks on real candidates, quarantines, threshold effects, and
  review rescue paths.
---

# Tour — How the quality gates decide

Same run as the [provenance tour](provenance-tour.md): `knovaryn demo`, the
deterministic offline pipeline on two bundled sample documents. **All content
is synthetic demo text.** Ten candidates went through validation; **3 passed,
6 were quarantined, 1 was routed to human review** — all three outcomes in one
small run, with the reason codes the gates emitted.

## The twelve gate dimensions

What each dimension checks, and what happened in this run:

| Dimension | What it checks | In this run |
|---|---|---|
| Schema | The example matches its topology's shape (messages, roles, fields). | Scored on all 10 candidates; all passed. |
| Grounding | The answer is supported by the *cited spans only* — scored against quoted evidence, not the whole document. | Scored; one candidate rejected with `low_grounding`, `grounding<0.9`, `critical_failed:grounding`. |
| Answerability | The prompt is actually answerable from the cited material. | Scored on all candidates; all passed. |
| Completeness | The answer covers what the prompt asks, per the cited spans. | Scored on all candidates; all passed. |
| Semantic consistency | The answer preserves the source's meaning (subject/object roles, negations, added claims). | One rejection: `subject_object_reversal` → `critical_failed:semantic_consistency`. |
| Duplicate detection | Content-hash dedup removes repeated rows before they ship. | Not exercised in the demo path (each candidate was unique); runs as a pipeline stage in full projects. |
| Contamination | Known eval-set overlap is flagged before export. | Not exercised in the demo (no eval corpus configured); runs in full projects. |
| Information gain | Preference pairs must separate the chosen answer meaningfully, not trivially. | The review-routed pair scored `trivial_separation` — the two answers differ by one appended sentence. |
| Preference signal | The chosen/rejected gap must clear a floor for preference topologies. | The pair scored `preference_signal<0.7` → routed to review, not exported. |
| Privacy | PII scanning at intake and before publication; findings block or flag. | Intake recorded a privacy classification for both demo sources (`unknown` — the synthetic texts carry no classification signal); the publication gate re-checks at publish time. |
| License | License status is recorded at intake and gates publication. | Both demo sources recorded `license_status: unknown` — and the demo bundle's license summary reports `status: review, count: 0` rather than pretending clearance. |
| Provenance integrity | Export re-resolves every citation; an example whose lineage cannot be walked is not exported. | Held for all 3 exported examples (see the [provenance tour](provenance-tour.md)). |

The run also scored format, refusal, instruction fulfillment, and
artifact resistance — the full per-candidate dimension set recorded on each
example as `quality_dimensions` with per-dimension verify states.

## The four outcomes

<div class="kn-tabs">
  <input type="radio" name="kn-gate-outcome" id="kn-gate-0" checked>
  <label for="kn-gate-0"><span class="kn-state kn-state--accepted">Pass</span></label>
  <input type="radio" name="kn-gate-outcome" id="kn-gate-1">
  <label for="kn-gate-1"><span class="kn-state kn-state--quarantined">Quarantine</span></label>
  <input type="radio" name="kn-gate-outcome" id="kn-gate-2">
  <label for="kn-gate-2"><span class="kn-state kn-state--review">Review required</span></label>
  <input type="radio" name="kn-gate-outcome" id="kn-gate-3">
  <label for="kn-gate-3"><span class="kn-state kn-state--quarantined">Unverified</span></label>

  <div class="kn-tabpanels">

    <section class="kn-panel">
      <h3>Pass — exported with its evidence</h3>
      <p>The accepted SFT example scored 1.0 across every scored dimension and
      every dimension's verify state is <code>verified</code> (one exception
      noted under <em>Unverified</em>). It became a member of dataset version
      <code>0.1.0</code> and shipped in <code>release.zip</code> with its span
      references, content hash, and quality record attached.</p>
      <div class="kn-evidence">
        <div class="kn-metric"><div class="kn-metric__label">Example</div><div class="kn-metric__value" style="font-size:0.8rem"><code>ex_01a03d42-29ab-7b0f-9c3d-a45cac20c1c1</code></div></div>
        <div class="kn-metric"><div class="kn-metric__label">Score</div><div class="kn-metric__value">1.0 — schema, grounding, answerability, completeness, semantic consistency, format, refusal, instruction fulfillment, artifact resistance</div></div>
        <div class="kn-metric"><div class="kn-metric__label">Destination</div><div class="kn-metric__value"><code>data/validation.jsonl</code> in <code>release.zip</code>, split <code>validation</code></div></div>
      </div>
    </section>

    <section class="kn-panel">
      <h3>Quarantine — rejected with reason codes, never exported</h3>
      <p>Six candidates were rejected. Two rejection signatures appeared:</p>
      <table>
        <thead><tr><th>Reason codes (verbatim)</th><th>Score</th><th>What happened</th></tr></thead>
        <tbody>
          <tr><td><code>subject_object_reversal</code>, <code>critical_failed:semantic_consistency</code></td><td>0.89</td><td>The answer swapped the source's subject and object. Semantic consistency is a critical dimension; a critical failure is a hard reject.</td></tr>
          <tr><td><code>low_grounding</code>, <code>grounding&lt;0.9</code>, <code>critical_failed:grounding</code></td><td>0.89</td><td>The answer was not sufficiently supported by the cited span. Grounding below the floor is a critical failure.</td></tr>
        </tbody>
      </table>
      <p>Quarantined rows keep their full lineage and reason codes in the
      workspace quarantine store — they are auditable, they just never enter a
      version or an export.</p>
    </section>

    <section class="kn-panel">
      <h3>Review required — a human decides</h3>
      <p>The preference pair scored below the preference-signal floor with four
      reason codes: <code>length_band_violation</code>,
      <code>trivial_separation</code>, <code>preference_signal&lt;0.7</code>,
      <code>artifact_resistance&lt;0.75</code>. None is a hard failure on its
      own — the separation is weak, which is exactly the judgment a human
      reviewer is better at than a heuristic. The pair waits in the review
      queue; <code>knovaryn review approve/reject</code> (or
      <code>knovaryn_review_example</code> over MCP) records the decision as an
      immutable revision with evidence.</p>
    </section>

    <section class="kn-panel">
      <h3>Unverified — recorded honestly, not passed silently</h3>
      <p>Even the accepted example carries one honest gap: its
      <code>artifact_resistance</code> dimension has verify state
      <code>unverified</code> (the demo's deterministic checks cannot certify
      that dimension without a configured judge). The example ships —
      artifact resistance is not a critical floor in the demo profile — but the
      gap is recorded on the example, visible in its quality metadata, instead
      of being silently treated as a pass. That is what
      <strong>fail-closed</strong> means in practice: dimensions that
      <em>are</em> critical and unverified block the row; dimensions that are
      not critical are exported with the gap stated.</p>
    </section>

  </div>
</div>

## What the gates do not claim

- **Deterministic heuristics do not prove general entailment.** The grounding
  and semantic-consistency checks are string- and role-level heuristics over
  the cited spans. They catch mechanical failures — reversals, unsupported
  additions, low overlap — not subtle untruths.
- **`certified-semantic` requires a configured judge.** Stricter semantic
  verification needs a judge model configured in your profile; the demo runs
  without one.
- **Unavailable judges fail closed.** If a profile demands judge certification
  and no judge is reachable, validation fails those dimensions rather than
  waving rows through.
- **License handling is not legal advice.** Knovaryn records license status
  and gates publication on your policy; it does not tell you what you may
  legally do with a source.

Reproduce the run behind this tour:

```bash
pip install knovaryn
knovaryn demo --examples 6 --json
```

Related: [quality gates concepts](../concepts/quality-gates.md) ·
[quality gates reference](../reference/quality-gates.md) ·
[validation profiles](../reference/profiles.md)
