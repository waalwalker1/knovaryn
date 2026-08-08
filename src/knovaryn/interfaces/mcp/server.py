"""Knovaryn MCP server (spec §17.2).

Exposes pipeline operations as MCP tools. The canonical server identity is
``knovaryn_mcp``. Requires the ``mcp`` package (extra). Tools wrap the
framework-free :class:`ProjectService`; the default demo tool runs offline with
the fake provider and requires no credentials.
"""

from __future__ import annotations

import asyncio
import importlib.util
from typing import Any

from ...domain.errors import ConfigurationError

SERVER_ID = "knovaryn_mcp"


def _mcp_available() -> bool:
    return importlib.util.find_spec("mcp") is not None


def build_server():
    """Construct the MCP fast server. Raises if ``mcp`` is not installed."""
    if not _mcp_available():
        raise ConfigurationError(
            "The MCP server requires the 'mcp' package. Install it (e.g. pip install mcp) "
            "or run Knovaryn via the CLI/REST instead."
        )
    from mcp.server.fastmcp import FastMCP

    from ...domain.ids import IdGenerator
    from ...domain.schemas import DatasetPlan, Project, SourceDocument, SourceKind

    mcp = FastMCP("Knovaryn", instructions="Training-data foundry pipeline tools.")

    @mcp.tool()
    def health() -> dict[str, Any]:
        """Health / identity check for the Knovaryn MCP server."""
        return {"status": "ok", "server_id": SERVER_ID, "product": "knovaryn"}

    @mcp.tool()
    def run_pipeline(task_families: str = "factual_explanation:0.5,procedure:0.3,comparison:0.2") -> dict[str, Any]:
        """Run the offline end-to-end pipeline on bundled sample documents.

        Args:
            task_families: comma-separated ``family:weight`` pairs for the plan.
        """
        from ...application.service import ProjectService

        proportions: dict[str, float] = {}
        for pair in task_families.split(","):
            if ":" in pair:
                fam, w = pair.split(":", 1)
                proportions[fam.strip()] = float(w.strip())
        if not proportions:
            proportions = {"factual_explanation": 1.0}

        ids = IdGenerator()
        project = Project(id=ids.new_handle("proj"), slug="demo", display_name="Knovaryn Demo", owner_principal="mcp")
        plan = DatasetPlan(task_family_proportions=proportions)

        sources: list[SourceDocument] = []
        contents: list[str] = []
        for name, text in _DEMO_SOURCES:
            sources.append(
                SourceDocument(
                    id=ids.new_handle("src"), project_id=project.id, original_name=name,
                    media_type="text/markdown", byte_size=len(text.encode()), sha256=ids.new_handle("d"),
                    source_kind=SourceKind.local_path, group_key=name,
                )
            )
            contents.append(text)

        svc = ProjectService(ids=ids)
        result = asyncio.run(svc.run_pipeline(project=project, sources=sources, contents=contents, plan=plan))
        payload = result.to_dict()
        payload["release_bundle_sha256"] = result.release_sha256
        return payload

    return mcp


_DEMO_SOURCES = [
    (
        "MLOps lifecycle overview",
        """# MLOps Lifecycle
## Data preparation
Data preparation is the first step of any machine learning project. It involves collecting raw data, cleaning it, and transforming it into a usable format. Practitioners must document the provenance of every data source to keep the dataset auditable.
## Model training
Model training consumes the prepared data. The training process optimizes model weights against a loss function. Hyperparameters such as the learning rate and batch size materially affect the final model quality.
## Evaluation
Evaluation measures model performance on held-out data. A held-out test set must never be used to tune hyperparameters.
""",
    ),
    (
        "Incident response runbook",
        """# Incident Response Runbook
## Triage
Upon receiving an alert, the on-call engineer first confirms the alert is genuine and not a false positive. The engineer classifies severity as low, medium, high, or critical.
## Containment
Containment isolates the affected component to prevent further damage. For a compromised service, this may mean rotating credentials and removing network egress.
## Recovery
Recovery restores service from a known-good backup. The team verifies data integrity before declaring recovery complete.
""",
    ),
]
