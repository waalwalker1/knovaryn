# Comparison — Knovaryn vs Docling SDK / Docling MCP

_Factual capability comparison, reviewed 2026-08. Capabilities are "documented
present / absent as of review"; projects move fast, so verify against the live
repos before relying on a claim. See also the [peer landscape](../peers/index.md)._

## What Docling is

Docling (IBM) is a document **conversion / parsing** library and MCP server for
high-fidelity extraction of PDFs and office documents into structured
representations (canonical DoclingDocument JSON, Markdown). Knovaryn **uses
Docling** as its canonical parsing layer (ADR 0003), so this comparison is
complementary rather than adversarial.

## Where they differ

| Concern | Knovaryn | Docling (SDK / MCP) |
|---|---|---|
| Scope | Training-data foundry (parse→split→generate→gate→export→publish) | Document parsing / conversion |
| Document → dataset | Yes (end-to-end) | No — parse only (you build the rest) |
| MCP surface | `knovaryn_mcp` (full dataset workflow: ingest → estimate → run → review → export) | Docling MCP (parsing tools) |
| Provenance | Span-level enforced lineage + content hash on examples | Returns structured docs for you to process |
| Quality gate | Fail-closed quarantine on generated examples | N/A (parsing) |
| Relation | Consumes Docling's canonical JSON | Provides the parse |

Docling is the right tool when you need the **best-in-class doc parsing**
surface by itself. Knovaryn is the right tool when you want to go **all the way
from permitted documents to a gated, exported, traceable training dataset** —
and it leans on Docling for the parsing step.

## When to choose Knovaryn

- You want a complete document-to-training-data pipeline, not just parsing.
- You want enforced **lineage**, quality **quarantine**, and durable jobs on top
  of the parse.
- You want to drive dataset construction from an **MCP-capable agent**.

## When Docling may fit better

- You need document conversion/extraction only, and will build your own training
  pipeline on top.

_No superiority claim is implied — Docling is the parsing dependency that makes
Knovaryn's fidelity possible. See the [peer landscape](../peers/index.md) for the
wider field._
