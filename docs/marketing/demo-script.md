# Knovaryn — 5-Minute Technical Demo Script

A scripted, reproducible walkthrough that shows the full loop: **permitted document → estimate → run → resume → review → quarantine → export → lineage.** The demo runs in the `offline-demo` profile with the deterministic fake provider, so it needs **no API keys and no network** beyond the initial install. All timings assume the local install is already done and warm.

> These are scripted commands, not exact CLI output. Captions in *italics* are the presenter's lines. Adjust where your terminal shows real values.

---

## 0. Setup (pre-checks, 30s)

```bash
knovaryn --version            # expect 0.1.0
knovaryn doctor               # checks profile, extras, state dir
```

*Presenter:* "Knovaryn is an open, MCP-native training-data foundry. In the next five minutes I'll turn one permissive PDF into a quality-gated SFT and preference dataset, kill the job mid-run to prove it resumes without duplicate spend, quarantine a weak example, and export for two trainers. Offline, no keys."

---

## 1. Create a project (30s)

```bash
knovaryn project create \
  --name "Knovaryn Launch Dataset" \
  --slug launch-dataset \
  --description "Demo: SFT + preference from a public-domain maintenance manual"
```

*Presenter:* "A `Project` is the container and the authorization boundary. Everything below hangs off this project ID."

---

## 2. Add a permissively-licensed PDF with a table (60s)

```bash
knovaryn source add \
  --project launch-dataset \
  ./fixtures/maintenance-manual-2021.pdf \
  --declared-license "CC0" \
  --kind upload
```

*Presenter:* "I'm adding a PDF that declares a permissive, redistributable license. Knovaryn preflights it — SHA-256, byte size, page count — and marks license status. Note the table: Docling parses it structurally, so the table boundary is preserved and reported as a table chunk."

Point at the source details:

```bash
knovaryn source show launch-dataset --source <id>
```

*Presenter:* "License status `allowed`, privacy classification set, intake `preflight_ok`. If the license were unknown it would land in `review` — and if it were blocked, Knovaryn would refuse to use it for a public export."

---

## 3. Estimate before you spend (30s)

```bash
knovaryn plan \
  --project launch-dataset \
  --topologies sft preference \
  --target 500 \
  --dry-run-cost
```

Shows: predicted chunks from structure-aware chunking, tokens across generator/critic/verifier, estimated cost under the active budget, expected yield.

*Presenter:* "Estimate is a dry run — no model calls. Plan asks for 500 examples across SFT and preference topologies, and Knovaryn reports what that should cost under `budget.maximum_cost_usd`. Nothing is spent on speculation."

---

## 4. Run via MCP (60s)

From a separate terminal, start the server:

```bash
knovaryn mcp --profile offline-demo
```

Then, from any MCP-capable agent, issue natural language:

> "Create project `launch-dataset`, add `./fixtures/maintenance-manual-2021.pdf` (CC0), and run the current plan with 500 SFT+preference examples on the balanced profile."

The agent maps this to MCP tools — `create_project`, `add_source`, `plan`, `run` — and streams progress via the job event stream.

*Presenter:* "The exact same pipeline I ran by hand in the CLI is now callable from any MCP-capable agent. The agent drives the tools; Knovaryn owns the durable state."

```bash
knovaryn run \
  --project launch-dataset \
  --profile balanced \
  --topologies sft preference
```

---

## 5. Resume after disconnect (60s)

Kill the worker mid-run:

```bash
# in a second shell, 30 seconds into the run
kill -TERM $(pidof knovaryn-worker)     # or Ctrl-C the MCP run
```

Then restart the same job. Because Knovaryn records output checkpoints and an idempotency key per job, the worker resumes from the last checkpoint rather than regenerating finished chunks:

```bash
knovaryn run --resume launch-dataset --job <id>
```

*Presenter:* "I just killed a worker in the middle of generation. On resume, Knovaryn reads the checkpoint, verifies which chunks already produced accepted candidates, and continues from exactly that point. The finished work is not redone — so the token spend isn't duplicated. For an expensive production run against a live provider, this is the difference between a 40-minute job that survives a bad Wi-Fi and a job that silently burns the budget twice."

Use a monitoring poll:

```bash
knovaryn job events --project launch-dataset --job <id> --follow
```

---

## 6. Review one SFT + one preference example (60s)

```bash
knovaryn review list --project launch-dataset --status review --topology sft --limit 1
knovaryn review show --project launch-dataset --example <sft-id>
knovaryn review list --status review --topology preference --limit 1
knovaryn review show --project launch-dataset --example <pref-id>
```

*Presenter (SFT row):* "Here's an SFT example: a procedural instruction drawn from the manual. See the evidence block — `source_document_ids` and `source_span_ids` point at the exact chunk and spans, plus the content hash. Grounding isn't a promise; it's a pointer you can open."

*Presenter (preference pair):* "And a preference pair: a prompt with a chosen and a rejected response, plus the `rejected_defect` taxonomy entry — here a `subtle_factual_error`. The pair passed the length-ratio band and the superficial-artifact separator, so it's a learning signal, not a formatting giveaway."

---

## 7. Show why a weak example was quarantined (30s)

```bash
knovaryn review list --project launch-dataset --status rejected --reason grounding<0.9
knovaryn review show --project launch-dataset --example <rejected-id>
```

*Presenter:* "This example was rejected, not just flagged. Its `quality_dimensions` show grounding below the 0.90 policy floor, so the acceptance gate quarantined it with a reason code — `grounding<0.9`. It does not reach any export. Knovaryn doesn't just count examples; it refuses the ones its policy says don't hold up."

---

## 8. Export for TRL and LLaMA-Factory (30s)

```bash
knovaryn export \
  --project launch-dataset \
  --version 0.1.0 \
  --format trl-conversational \
  --format llamafactory-sharegpt \
  --format parquet
```

*Presenter:* "Three formats from one canonical versioned dataset: TRL conversational for fine-tuning with the TRL/SFT library, LLaMA-Factory ShareGPT, and Parquet for analysis. Whatever your trainer, you don't rewrite the pipeline."

---

## 9. Open the dataset card / lineage (30s)

```bash
knovaryn dataset card   --project launch-dataset --version 0.1.0
knovaryn dataset lineage --project launch-dataset --example <sft-id>
```

*Presenter:* "The dataset card records train/validation/test counts, source manifest, license report, quality report. And from any example I can walk the lineage: example → generation candidate → chunk → parsed document (Docling) → source document → original PDF page. That chain is what makes the dataset *defensible* — every row can be defended to a reviewer, a client, or a regulator."

---

## Close (30s)

*Presenter:* "Permissioned-in document in, traceable, quality-gated, trainer-ready data out — surviving a kill, with every example pointed at its source and every rejection justified. Everything you saw is on GitHub under Apache-2.0, and the offline demo needs no credentials. Links are in the repo README."

**Total:** ~5 minutes.

---

## Notes for the presenter

- Run the full flow once yourself before the demo; the fake provider is deterministic, so timings are stable.
- Keep the "kill the worker" step safe: in a live-provider demo, resume honors the budget and idempotency, but don't run it against a billable provider unless you intend to (and monitor `actual_cost`).
- If a table isn't available, any PDF with clear structure works; the point is that tables survive as table chunks with their own evidence spans.
- Do **not** claim Knovaryn guarantees bias-free or hallucination-free output, or that the resulting dataset improves any model. Frame rejected examples as *policy-gated*, not *proven wrong*.
