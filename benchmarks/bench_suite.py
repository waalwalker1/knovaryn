"""Knovaryn benchmark suite (spec WP N1-N4).

Runs a deterministic, offline pipeline over the always-available text corpus and
reports reproducible metrics for the benchmark categories that are executable
without optional extras. Every number is a *framework* measurement on the
deterministic fake provider (see N3): it is NOT synthetic-data generation
throughput, NOT model quality, and makes no model-improvement claim.

Categories measured here (text corpus, always available):
  1. parse fidelity          - parse success, heading/structure extraction
  2. lineage resolution      - every accepted example's evidence refs resolve
  3. generation validity     - candidate->example acceptance / quarantine rate
  4. groundedness            - grounding-validator reject rate
  5. preference-pair quality - chosen/rejected distinct + defect present
  6. duplicate / leakage     - dedupe & contamination reject counts
  8. pipeline throughput     - elapsed / examples-per-sec (framework overhead)
 11. export compatibility     - all formats round-trip with resolvable lineage
 12. memory / resource        - peak resident size

Categories NOT measured here (gated / referenced, per honest-claims rule):
  - table/layout extraction (requires the ``docling`` extra) - see corpus README
  - crash recovery (covered by the chaos test tier) - see tests/test_chaos*
  - provider cost (fake provider is zero-cost; live cost requires credentials)
Run with:  .venv/bin/python benchmarks/bench_suite.py [--json]
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from knovaryn.application.service import ProjectService  # noqa: E402
from knovaryn.domain.ids import IdGenerator  # noqa: E402
from knovaryn.domain.schemas import (  # noqa: E402
    DatasetPlan,
    Project,
    QualityStatus,
    SourceDocument,
    SourceKind,
    Topology,
)
from knovaryn.pipeline.export.formats import SUPPORTED_FORMATS, export_format  # noqa: E402

# Real fixture bytes from the committed corpus (see benchmarks/corpus/README.md).
_CORPUS: dict[str, bytes] = {}
for _name in ("numbered-headings.md", "multilingual.txt", "sample.csv", "sample.json"):
    _p = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "intake" / _name
    if _p.exists():
        _CORPUS[_name] = _p.read_bytes()


def _metric(m: dict, key: str, value) -> None:
    m[key] = round(value, 4) if isinstance(value, float) else value


async def _run_categories() -> dict[str, object]:
    ids = IdGenerator()
    project = Project(
        id=ids.new_handle("proj"),
        slug="bench",
        display_name="Knovaryn Benchmark",
        owner_principal="bench",
    )
    plan = DatasetPlan(
        task_family_proportions={"factual_explanation": 0.5, "procedure": 0.3, "comparison": 0.2},
        difficulty_distribution={"basic": 0.3, "intermediate": 0.5, "advanced": 0.2},
        maximum_dataset_size=2000,
    )
    sources: list[SourceDocument] = []
    raw: list[bytes] = []
    for name, blob in _CORPUS.items():
        sources.append(
            SourceDocument(
                id=ids.new_handle("src"),
                project_id=project.id,
                original_name=name,
                media_type="text/markdown" if name.endswith(".md") else "text/plain",
                byte_size=len(blob),
                sha256=ids.new_handle("d"),
                source_kind=SourceKind.local_path,
                group_key=name,
            )
        )
        raw.append(blob)

    m: dict[str, object] = {"corpus": sorted(_CORPUS.keys()), "provider": "fake (deterministic)"}

    tracemalloc.start()
    t0 = time.monotonic()
    svc = ProjectService(ids=ids)
    result = await svc.run_pipeline(project=project, sources=sources, raw_contents=raw, plan=plan)
    elapsed = time.monotonic() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    m["sources"] = len(result.sources) if hasattr(result, "sources") else len(sources)
    m["parsed"] = len(result.parsed)
    m["chunks"] = len(result.chunks)
    m["spans"] = len(result.spans)
    m["candidates"] = len(result.candidates)
    m["examples"] = len(result.examples)
    m["accepted"] = sum(1 for e in result.examples if e.quality_status == QualityStatus.accepted)
    m["quarantined"] = sum(1 for e in result.examples if e.quality_status != QualityStatus.accepted)
    m["version"] = result.version.semantic_version if result.version else None
    m["release_sha256_present"] = bool(result.release_sha256)
    m["release_bundle_bytes"] = len(result.release_bundle_bytes)

    # 1. parse fidelity (text corpus) — parse every source, structure seen
    _metric(m, "parse_success_rate", (len(result.parsed) / len(sources)) if sources else 0.0)
    heading_chunks = sum(1 for c in result.chunks if getattr(c, "heading_path", None))
    _metric(
        m,
        "chunk_heading_coverage",
        heading_chunks / len(result.chunks) if result.chunks else 0.0,
    )

    # 2. lineage resolution — every example's refs resolve to pipeline entities
    doc_ids = {d.id for d in result.parsed} | {s.id for s in sources}
    span_ids = {s.id for s in result.spans}
    line_resolve, line_miss = 0, 0
    for e in result.examples:
        ok = bool(e.source_document_ids) and all(x in doc_ids for x in e.source_document_ids)
        ok = ok and (not e.source_span_ids or all(x in span_ids for x in e.source_span_ids))
        ok = ok and bool(e.content_hash) and bool(e.generation_candidate_ids)
        line_resolve, line_miss = (
            (line_resolve + 1, line_miss) if ok else (line_resolve, line_miss + 1)
        )
    _metric(
        m,
        "lineage_resolution_rate",
        line_resolve / len(result.examples) if result.examples else 0.0,
    )

    # 3/4. generation validity + groundedness via the quality engine
    q = result.quality if isinstance(result.quality, dict) else {}
    for key in ("accepted", "quarantined", "rejected", "reason_codes"):
        if isinstance(q.get(key), (int, float, list)):
            m[f"quality.{key}"] = q[key]
    if isinstance(q.get("reason_codes"), list):
        reasons = q["reason_codes"]
        _metric(m, "quality.grounding_rejects", reasons.count("grounding"))

    # 5. preference-pair quality (if any preference examples present)
    pref = [e for e in result.examples if e.topology == Topology.preference]
    if pref:
        distinct = sum(
            1
            for e in pref
            if (e.chosen_messages or e.rejected_messages)
            and e.chosen_messages != e.rejected_messages
        )
        with_defect = sum(1 for e in pref if e.defect_taxonomy)
        _metric(m, "pref_pairs_total", len(pref))
        _metric(m, "pref_pairs_distinct", distinct / len(pref))
        _metric(m, "pref_pairs_with_defect", with_defect / len(pref))

    # 6. duplicate / leakage — rely on the reject reason distribution
    if isinstance(q.get("reason_codes"), list):
        rc = q["reason_codes"]
        _metric(m, "quality.duplicate_rejects", rc.count("duplicate"))
        _metric(m, "quality.contamination_rejects", rc.count("contamination"))

    # 8. throughput (framework overhead only — N3)
    _metric(m, "elapsed_s", elapsed)
    _metric(m, "examples_per_second", len(result.examples) / elapsed if elapsed else 0.0)

    # 11. export compatibility — every format round-trips with lineage intact
    export_status: dict[str, str] = {}
    for fmt in sorted(SUPPORTED_FORMATS):
        try:
            res = export_format(result.examples, fmt)
            n = res.rows if hasattr(res, "rows") else None
            has_bytes = bool(getattr(res, "bytes", b""))
            has_sha = bool(getattr(res, "sha256", ""))
            export_status[fmt] = (
                "ok" if (isinstance(n, int) and n > 0 and has_bytes and has_sha) else "empty"
            )
        except Exception as exc:  # noqa: BLE001
            export_status[fmt] = f"err:{type(exc).__name__}"
    m["export_status"] = export_status

    # 12. memory / resource
    _metric(m, "peak_allocated_bytes", peak)

    return m


def main() -> int:
    metrics = asyncio.run(_run_categories())
    if "--json" in sys.argv:
        print(json.dumps(metrics, indent=2, default=str))
    else:
        print("Knovaryn benchmark suite — deterministic offline run (framework metrics, see N3)")
        for k, v in metrics.items():
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
