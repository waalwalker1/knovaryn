"""Knovaryn offline pipeline benchmark (spec §24.3).

Measures end-to-end throughput of the offline (fake-provider) pipeline on bundled
sample documents. Deterministic: same inputs produce the same dataset every run,
so timings isolate the framework cost (parsing, chunking, generation, validation,
export). Run with:  .venv/bin/python benchmarks/bench_pipeline.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from knovaryn.application.service import ProjectService  # noqa: E402
from knovaryn.domain.ids import IdGenerator  # noqa: E402
from knovaryn.domain.schemas import DatasetPlan, Project, SourceDocument, SourceKind  # noqa: E402

_SOURCES = [
    (
        "MLOps lifecycle",
        """# MLOps Lifecycle
## Data preparation
Data preparation is the first step of any machine learning project. It involves collecting raw data, cleaning it, and transforming it into a usable format. Practitioners must document the provenance of every data source to keep the dataset auditable.
## Model training
Model training consumes the prepared data. The training process optimizes model weights against a loss function. Hyperparameters such as the learning rate and batch size materially affect the final model quality.
## Evaluation
Evaluation measures model performance on held-out data. A held-out test set must never be used to tune hyperparameters, because doing so leaks signal and inflates reported accuracy.
## Deployment and monitoring
Once deployed, models require ongoing monitoring for drift. Concept drift occurs when the statistical properties of the input distribution change over time.""",
    ),
    (
        "Runbook",
        """# Incident Response Runbook
## Triage
Upon receiving an alert, the on-call engineer first confirms the alert is genuine and not a false positive. The engineer classifies severity as low, medium, high, or critical.
## Containment
Containment isolates the affected component to prevent further damage. For a compromised service, this may mean rotating credentials and removing network egress.
## Recovery
Recovery restores service from a known-good backup. The team verifies data integrity before declaring recovery complete.""",
    ),
]


async def _run() -> dict[str, float | int]:
    ids = IdGenerator()
    project = Project(id=ids.new_handle("proj"), slug="bench", display_name="Knovaryn Benchmark", owner_principal="bench")
    plan = DatasetPlan(
        task_family_proportions={"factual_explanation": 0.5, "procedure": 0.3, "comparison": 0.2},
        difficulty_distribution={"basic": 0.3, "intermediate": 0.5, "advanced": 0.2},
        maximum_dataset_size=2000,
    )
    sources: list[SourceDocument] = []
    contents: list[str] = []
    for name, text in _SOURCES:
        sources.append(
            SourceDocument(
                id=ids.new_handle("src"), project_id=project.id, original_name=name,
                media_type="text/markdown", byte_size=len(text.encode()), sha256=ids.new_handle("d"),
                source_kind=SourceKind.local_path, group_key=name,
            )
        )
        contents.append(text)

    svc = ProjectService(ids=ids)
    t0 = time.monotonic()
    result = await svc.run_pipeline(project=project, sources=sources, contents=contents, plan=plan)
    elapsed = time.monotonic() - t0
    return {
        "elapsed_s": round(elapsed, 3),
        "sources": len(sources),
        "chunks": len(result.chunks),
        "examples": len(result.examples),
        "accepted": sum(1 for e in result.examples if e.quality_status.value == "accepted"),
        "release_bytes": len(result.release_bundle_bytes),
        "examples_per_second": round(len(result.examples) / elapsed, 2) if elapsed else 0.0,
    }


def main() -> None:
    metrics = asyncio.run(_run())
    for k, v in metrics.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
