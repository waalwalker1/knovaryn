# Show HN / Reddit post — draft

*Style note: This is the "I built X, here's what it does and what it doesn't do" version — factual, no hype, no marketing superlatives. Works as a Show HN ("Show HN: ...") and as an r/LocalLLaMA / r/MachineLearning self-post.*

---

**Title: Show HN: Knovaryn — MCP-native training-data foundry (documents → traceable SFT/preference datasets)**

I've been building fine-tuning datasets from documents by hand, and the painful part was never the model calls — it's the bookkeeping. Every row needs to point at the source it came from, weak examples need to be caught instead of shipped, and a generation job that dies at minute 35 shouldn't make me pay for those 35 minutes again.

So I built **Knovaryn** — open source, Apache-2.0, Python ≥ 3.11. It's a document-to-dataset pipeline that's MCP-native, meaning an MCP-capable agent (Claude Code or any MCP client) can drive the whole thing in natural language. The CLI exposes the same pipeline if you'd rather not use an agent.

**The pipeline:** project → add a permissively-licensed document → parse (Docling) → structure-aware chunking (tables and lists stay together) → plan with a dry-run cost estimate → durable run → validation → human review → split/version → export.

**What I think is worth a look:**

1. **Evidence is part of the data model.** Every generated example carries references to the source document, the specific spans it came from, a content hash, and the generation candidates. You can walk from any example back to the page and section of the PDF. No "trust me, it's grounded" — it's a pointer.

2. **Jobs are durable and idempotent.** Workers lease jobs with heartbeats and checkpoints. Kill a worker mid-run and the job resumes from its checkpoint instead of regenerating finished chunks. For billable generation that's real money saved.

3. **Bring your own model and trainer.** Provider adapters behind a `ModelGateway` port (OpenAI-compatible, Anthropic-compatible, DeepSeek). There's a deterministic fake provider, so the whole pipeline runs offline with zero credentials. Exporters produce TRL conversational, LLaMA-Factory ShareGPT, canonical JSONL, and Parquet.

4. **Quality is gated, not assumed.** Candidates get scored (grounding, instruction fulfillment, preference signal, artifact resistance) against a configurable acceptance policy, and weak examples are quarantined with a reason code (e.g. `grounding<0.9`) instead of silently included. Released versions come with dataset cards and quality reports.

**Honest limitations, up front:**

- This is a 0.1.0 alpha. APIs will change before 1.0; I've documented a release gate for that.
- Validation measures grounding and artifact-resistance against a **policy I configured** — it does not guarantee bias-free or hallucination-free data, and I make no claim that using it improves any model.
- License handling classifies declared/detected licenses and refuses blocked/unknown sources for public export. That's a safety rail, **not** legal clearance — do your own review for anything regulated.
- The quality heuristics are heuristic. I'd genuinely like critiques of them.

**Try it (no keys needed for the offline demo):**

```bash
pip install -e ".[dev]"
knovaryn init
knovaryn mcp --profile offline-demo
```

The repo has a five-minute demo script (includes killing a worker mid-run to show the resume, and quarantining a weak example), a benchmark methodology, and a peer-comparison that's honest about where this overlaps with existing tools like meta's Synthetic Data Kit, Argilla Distilabel, and DocETL.

GitHub links in the repo README. Would love feedback — especially on the validation heuristics and whether the MCP-first interface is actually useful to people or just novelty.

---

*(Reddit tip: keep the title factual, post the body, answer questions in comments; avoid "revolutionary/amazing." HN tip: the interesting discussions will be about whether MCP-first data engineering is a good idea and whether LLM-judge-based quality gating is trustworthy — engage honestly.)*
