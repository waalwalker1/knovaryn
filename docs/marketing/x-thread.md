# Knovaryn — X (Twitter) thread (draft)

*Numbered posts. Short, factual, honest. Thread title / first-post hashtag suggestions at the end. Max ~280 chars each; trim if editor flags.*

---

**1/8**
We open-sourced Knovaryn — a training-data foundry that turns permitted documents into traceable, quality-gated SFT & preference datasets. Apache-2.0, MCP-native, Python ≥ 3.11. Code + quickstart in the repo. #LLM #MCP #MachineLearning

**2/8**
The gap we're after: model APIs and trainers got easy; the *data* didn't. Most pipelines can't tell you where a row came from, lose work to disconnects, and lock you into one format. Knovaryn is built around 5 mechanisms.

**3/8**
1) Evidence is a first-class property. Every example carries source-doc + span refs, a content hash, and lineage back to the page & section of the PDF. "Grounded" is a pointer you open, not a promise.

**4/8**
2) Durable, resumable jobs. Idempotent, checkpointed workers. Kill one mid-run and it resumes from the checkpoint — finished chunks aren't regenerated, so no double token spend.

**5/8**
3) Bring your own model & trainer. OpenAI-compatible / Anthropic-compatible / DeepSeek adapters behind a gateway. A deterministic fake provider runs the whole pipeline offline, no keys. Export: TRL, LLaMA-Factory, JSONL, Parquet.

**6/8**
4) Run local or governed. Offline-demo profile for individuals; scope-based access + admin policy for teams. 5) Measure, don't just generate — candidates are scored (grounding, instruction fulfillment, preference signal, artifact resistance); weak examples are quarantined with a reason.

**7/8**
MCP-native: start `knovaryn mcp` and any MCP-capable agent drives the whole loop in natural language — create project, add PDF, estimate with --dry-run-cost, run, review, export.

**8/8**
Honest limits: 0.1.0 alpha, APIs will change before 1.0. No claim of bias-free data or guaranteed model improvement; license handling is a gate, not legal clearance. 5-min demo script shows resume-after-kill + quarantine. Feedback welcome → repo.

---

**Hashtags (optional):** #LLM #MCP #MachineLearning #OpenSource #SFT #FineTuning #LLMOps

**Drafting notes:** This is intentionally a 8-post draft — compress to the strongest 5–6 before posting to keep it readable. Pair with a screenshot of `knovaryn mcp` output in post 2 and the lineage/output of a dataset card in post 6. Never attach claims of bias/hallucination freedom or "improves your model" to any post.
