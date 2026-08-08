# Knovaryn — LinkedIn announcement (draft)

**Post for the announcement, professional tone. Draft; verify links before publishing.**

---

We're open-sourcing something we've been thinking about for a while: **Knovaryn**, an MCP-native training-data foundry — Apache-2.0, Python ≥ 3.11, now at 0.1.0.

**The idea in one line.** Turn documents you're permitted to use into SFT and preference datasets that are *traceable* (every example points back to its source page and section) and *quality-gated* (weak examples are quarantined with a reason, not silently shipped).

Small applied-LLM teams keep hitting the same wall: the model APIs and the trainers (TRL, LLaMA-Factory) got easy, but the **data still isn't**. Most generation pipelines can't tell you where any given row came from, can't survive a dropped connection without double-spending tokens, and dump you into one trainer's format.

**What Knovaryn does differently:**

- **Evidence as a first-class property.** Each generated example carries source-document and source-span references, a content hash, and full lineage back to the original document.
- **Durable, resumable jobs.** Checkpointed, idempotent workers recover from a disconnect without regenerating finished work — no duplicate token spend.
- **Bring your own model and trainer.** Provider adapters (OpenAI-compatible, Anthropic-compatible, DeepSeek) behind a model gateway; a deterministic fake provider runs the whole pipeline offline with no keys. Export to TRL, LLaMA-Factory ShareGPT, JSONL, or Parquet.
- **Run local or governed.** An offline demo profile for individuals; scope-based access and admin policy for teams.
- **Measure, don't just generate.** Candidates are scored against a configurable acceptance policy; rejected examples are quarantined with reason codes.

**A deliberate caveat:** this is an early alpha, and we're keeping the limitations as public as the features — no claim of bias-free or hallucination-free data, no guarantee that generated data improves any model, and license handling is a safety rail, not legal clearance. The release gate and benchmark methodology are public in the repo.

The offline demo needs no API keys, and the MCP server lets any MCP-capable agent drive the whole pipeline in natural language.

Try it, break it, and tell us what the validation heuristics get wrong. We'd welcome contributors across providers, exporters, and quality heuristics.

🔗 Links and quickstart: see the repo README and `docs/marketing/`.

*— The Knovaryn maintainers*

---

*(Optional second post, later in launch week — "What we learned shipping an MCP-first data tool": talk about what agents do well and badly at driving data pipelines, honestly.)*
