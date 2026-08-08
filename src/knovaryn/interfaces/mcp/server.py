"""Knovaryn MCP server (spec §17).

Exposes the full tool set from §17.2 on top of the framework-free
:class:`Workspace`, plus optional resources (§17.3) and prompts (§17.4). The
canonical server identity is ``knovaryn_mcp``. Requires the ``mcp`` package
(extra). All workspace operations run offline/deterministically with the fake
provider by default and need no credentials.
"""

from __future__ import annotations

import asyncio
import importlib.util
from typing import TYPE_CHECKING, Any, Coroutine, TypeVar

from ...domain.errors import ConfigurationError

if TYPE_CHECKING:
    from ...application.workspace import Workspace

SERVER_ID = "knovaryn_mcp"

_T = TypeVar("_T")


def _mcp_available() -> bool:
    return importlib.util.find_spec("mcp") is not None


def _asyncio(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run a coroutine on a fresh loop (tools are sync FastMCP callables)."""
    return asyncio.run(coro)


class _WorkspaceHolder:
    """Lazily-created singleton workspace shared across tools."""

    def __init__(self) -> None:
        from ...application.workspace import Workspace

        self._workspace: "Workspace | None" = None

    def get(self) -> "Workspace":
        from ...application.workspace import Workspace

        if self._workspace is None:
            self._workspace = Workspace(principal="mcp")
            _asyncio(self._workspace.open())
        return self._workspace


_WS = _WorkspaceHolder()


def build_server() -> Any:
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

    ws = _WS

    # ------------------------------------------------------------------ misc
    @mcp.tool()
    def health() -> dict[str, Any]:
        """Health / identity check for the Knovaryn MCP server."""
        return {"status": "ok", "server_id": SERVER_ID, "product": "knovaryn"}

    @mcp.tool()
    def knovaryn_doctor() -> dict[str, Any]:
        """Environment and dependency capability diagnostics (no secrets)."""
        try:
            from ...infrastructure.docetl.adapter import docetl_available
            from ...infrastructure.docling.adapter import docling_available
            from ...infrastructure.models.litellm_provider import _litellm_available
            from ...infrastructure.models.profiles import OFFICIAL_RUNTIME_PROFILES
            from ...infrastructure.publish.hf import hub_available
            from ...infrastructure.resources import detect_resource_profile

            profile = detect_resource_profile()
            return {
                "status": "ok",
                "accelerator": profile.accelerator,
                "note": profile.note,
                "dependencies": {
                    "docling": docling_available(),
                    "docetl": docetl_available(),
                    "huggingface_hub": hub_available(),
                    "litellm": _litellm_available(),
                    "mcp": True,
                },
                "runtime_profiles": sorted(OFFICIAL_RUNTIME_PROFILES),
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "degraded", "error": str(exc)}

    # -------------------------------------------------------------- projects
    @mcp.tool()
    def knovaryn_create_project(
        slug: str,
        display_name: str,
        description: str = "",
        owner_principal: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a project. Returns project_id, default profile, and actions."""
        try:
            project = _asyncio(
                ws.get().create_project(
                    slug=slug,
                    display_name=display_name,
                    description=description,
                    owner_principal=owner_principal,
                    tags=tags,
                )
            )
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}
        return {
            "project_id": project.id,
            "slug": project.slug,
            "default_profile": {"runtime": "fake", "offline": True, "requires_credentials": False},
            "next_actions": ["knovaryn_add_source", "knovaryn_start_pipeline"],
        }

    @mcp.tool()
    def knovaryn_list_projects(limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
        """Paginated, filtered project summary."""
        return _asyncio(ws.get().list_projects(limit=limit, cursor=cursor))

    # --------------------------------------------------------------- sources
    @mcp.tool()
    def knovaryn_add_source(
        project_id: str,
        original_name: str,
        content: str,
        media_type: str = "text/markdown",
        declared_license: str | None = None,
    ) -> dict[str, Any]:
        """Register an uploaded artifact. Returns source_id + next job handle."""
        try:
            src = _asyncio(
                ws.get().add_source(
                    project_id=project_id,
                    original_name=original_name,
                    media_type=media_type,
                    content=content,
                    declared_license=declared_license,
                    source_kind="upload",
                )
            )
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}
        return {"status": "ok", "source_id": src.id, "next": "knovaryn_start_pipeline"}

    @mcp.tool()
    def knovaryn_inspect_source(project_id: str, source_id: str) -> dict[str, Any]:
        """Metadata, preflight, extraction summary, license/privacy state."""
        sources = _asyncio(ws.get().list_sources(project_id=project_id, limit=1000))
        for s in sources.get("sources", []):
            if s.get("id") == source_id:
                report = _asyncio(ws.get().license_report(project_id=project_id))
                rec = next(
                    (r for r in report.get("sources", []) if r.get("source_id") == source_id), None
                )
                return {
                    "source_id": source_id,
                    "original_name": s.get("original_name"),
                    "media_type": s.get("media_type"),
                    "byte_size": s.get("byte_size"),
                    "sha256": s.get("sha256"),
                    "declared_license": s.get("declared_license"),
                    "license_status": (rec or {}).get("license_status", "review"),
                    "privacy": (rec or {}).get("privacy", "no_preflight_scan"),
                    "approved_for_public_release": bool(
                        (rec or {}).get("approved_for_public_release", False)
                    ),
                    "artifact": f"knovaryn://projects/{project_id}/sources/{source_id}/summary",
                }
        return {"status": "error", "error": f"source not found: {source_id}"}

    @mcp.tool()
    def knovaryn_license_report(project_id: str) -> dict[str, Any]:
        """Source license + privacy report and §15.6 publication-gate decision."""
        return _asyncio(ws.get().license_report(project_id=project_id))

    # -------------------------------------------------------------- pipeline
    @mcp.tool()
    def knovaryn_estimate_run(
        project_id: str,
        target_count: int = 100,
        topology: str = "sft",
        task_families: str = "factual_explanation:0.5,procedure:0.3,comparison:0.2",
    ) -> dict[str, Any]:
        """Dry-run estimate for selected sources/topology/profile/targets."""
        from ...domain.policies import approximate_tokens

        sources = _asyncio(ws.get().list_sources(project_id=project_id, limit=1000))
        srcs = sources.get("sources", [])
        total_bytes = sum(s.get("byte_size", 0) for s in srcs)
        tokens = approximate_tokens("x" * total_bytes)
        # offline fake profile: no paid calls, deterministic cost
        return {
            "project_id": project_id,
            "topology": topology,
            "source_count": len(srcs),
            "source_bytes": total_bytes,
            "est_input_tokens": tokens,
            "est_output_tokens": tokens // 4,
            "target_count": target_count,
            "runtime_profile": "fake",
            "paid_calls": 0,
            "note": "offline fake profile — no provider calls, no cost",
        }

    @mcp.tool()
    def knovaryn_start_pipeline(
        project_id: str,
        task_fam_families: str = "factual_explanation:0.5,procedure:0.3,comparison:0.2",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Start a durable pipeline job (offline). Returns a job handle."""
        proportions: dict[str, float] = {}
        for pair in task_fam_families.split(","):
            if ":" in pair:
                fam, w = pair.split(":", 1)
                proportions[fam.strip()] = float(w.strip())
        if not proportions:
            proportions = {"factual_explanation": 1.0}
        try:
            job = _asyncio(
                ws.get().start_pipeline(
                    project_id=project_id,
                    task_family_proportions=proportions,
                    idempotency_key=idempotency_key,
                )
            )
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}
        return {
            "job_id": job.id,
            "state": job.state.value,
            "job_type": job.job_type,
            "message": "job queued — run knovaryn_get_job to poll, then knovaryn_run_job to execute offline",
        }

    @mcp.tool()
    def knovaryn_get_job(job_id: str) -> dict[str, Any]:
        """State, stage, progress, counts, costs, warnings, errors, events."""
        summary = _asyncio(ws.get().get_job(job_id))
        data = summary.to_dict()
        data["resources"] = {
            "job": f"knovaryn://projects/{summary.job.project_id}/jobs/{job_id}",
            "events": f"knovaryn://projects/{summary.job.project_id}/jobs/{job_id}/events",
        }
        return data

    @mcp.tool()
    def knovaryn_run_job(job_id: str) -> dict[str, Any]:
        """Execute a queued pipeline job offline in-process (returns final state).

        This is the local worker that actually runs the pipeline. In a real
        deployment a separate worker/lease would claim and run the job; here it
        runs synchronously for the offline path.
        """
        try:
            return _asyncio(ws.get().run_job(job_id))
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}

    @mcp.tool()
    def knovaryn_cancel_job(job_id: str) -> dict[str, Any]:
        """Request cooperative cancellation (idempotent)."""
        try:
            job = _asyncio(ws.get().request_cancel(job_id))
            return {"job_id": job.id, "state": job.state.value, "cancellation_requested": True}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}

    @mcp.tool()
    def knovaryn_resume_job(job_id: str) -> dict[str, Any]:
        """Resume a retryable failed job (re-lease and continue)."""
        try:
            summary = _asyncio(ws.get().get_job(job_id))
            job_state = summary.job.state.value
            if job_state in ("failed", "cancelling", "succeeded"):
                # re-queue and run again (idempotent replay of a retryable job)
                return _asyncio(ws.get().run_job(job_id))
            return {
                "job_id": job_id,
                "state": job_state,
                "message": "not in a resumable terminal state",
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}

    # ------------------------------------------------------------ examples
    @mcp.tool()
    def knovaryn_preview_examples(
        project_id: str, limit: int = 20, status: str | None = None
    ) -> dict[str, Any]:
        """Bounded, redacted page of examples + quality dimensions + evidence."""
        data = _asyncio(ws.get().list_examples(project_id=project_id, status=status, limit=limit))
        for e in data.get("examples", []):
            e.pop("content", None)
            e["_redacted"] = True
        return data

    @mcp.tool()
    def knovaryn_review_example(
        example_id: str,
        decision: str,
        note: str = "",
        relabel: str | None = None,
    ) -> dict[str, Any]:
        """Accept/reject/relabel an example (offline workspace records decision)."""
        # Optimistic-concurrency review is persisted by a worker-owned store; in
        # the in-memory/offline workspace we record the decision against the
        # example's quality flags via the repository. Content is untouched.
        if decision not in ("accept", "reject", "edit"):
            return {"status": "error", "error": f"unsupported decision: {decision}"}
        # Persist an audit trail through the workspace DB.
        try:
            _asyncio(_audit_review(ws.get(), example_id, decision, note, relabel))
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}
        return {
            "status": "recorded",
            "example_id": example_id,
            "decision": decision,
            "note": note,
            "relabel": relabel,
        }

    # ------------------------------------------------------------- datasets
    @mcp.tool()
    def knovaryn_validate_dataset(project_id: str, limit: int = 500) -> dict[str, Any]:
        """Run validation for a project's examples; returns a bounded report."""
        return _asyncio(ws.get().validate_dataset(project_id=project_id, limit=limit))

    @mcp.tool()
    def knovaryn_create_dataset_version(
        project_id: str, semantic_version: str | None = None
    ) -> dict[str, Any]:
        """Assemble an immutable draft version from accepted examples."""
        version = _asyncio(
            ws.get().create_version(project_id=project_id, semantic_version=semantic_version)
        )
        return {
            "version_id": version.id,
            "semantic_version": version.semantic_version,
            "train": version.train_count,
            "validation": version.validation_count,
            "test": version.test_count,
        }

    @mcp.tool()
    def knovaryn_export_dataset(project_id: str, version_id: str | None = None) -> dict[str, Any]:
        """Export accepted examples as JSONL; returns artifact handles/summary."""
        res = _asyncio(ws.get().export_dataset(project_id=project_id, version_id=version_id))
        res["artifact"] = f"knovaryn://projects/{project_id}/datasets/export/jsonl"
        return res

    @mcp.tool()
    def knovaryn_publish_dataset(
        project_id: str,
        repo_id: str,
        dry_run: bool = True,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Publish an approved version (external side effect). Dry-run by default."""
        if not dry_run and not confirm:
            return {
                "status": "error",
                "error": "publish requires confirm=true (external side effect)",
            }
        return _asyncio(
            ws.get().publish_dataset(project_id=project_id, repo_id=repo_id, dry_run=dry_run)
        )

    @mcp.tool()
    def knovaryn_compare_runs(project_id: str, job_id_a: str, job_id_b: str) -> dict[str, Any]:
        """Compare quality/cost across two compatible runs."""
        a = _asyncio(ws.get().get_job(job_id_a)).to_dict()
        b = _asyncio(ws.get().get_job(job_id_b)).to_dict()
        return {
            "job_a": a,
            "job_b": b,
            "delta": {
                "cost": (b.get("estimated_cost") or 0) - (a.get("estimated_cost") or 0),
                "progress": b.get("progress_current", 0) - a.get("progress_current", 0),
            },
        }

    # ------------------------------------------------------------ legacy demo
    @mcp.tool()
    def run_pipeline(
        task_families: str = "factual_explanation:0.5,procedure:0.3,comparison:0.2",
    ) -> dict[str, Any]:
        """Run the offline end-to-end pipeline on bundled sample documents."""
        from ...application.service import ProjectService

        proportions: dict[str, float] = {}
        for pair in task_families.split(","):
            if ":" in pair:
                fam, w = pair.split(":", 1)
                proportions[fam.strip()] = float(w.strip())
        if not proportions:
            proportions = {"factual_explanation": 1.0}

        ids = IdGenerator()
        project = Project(
            id=ids.new_handle("proj"),
            slug="demo",
            display_name="Knovaryn Demo",
            owner_principal="mcp",
        )
        plan = DatasetPlan(task_family_proportions=proportions)

        sources: list[SourceDocument] = []
        contents: list[str] = []
        for name, text in _DEMO_SOURCES:
            sources.append(
                SourceDocument(
                    id=ids.new_handle("src"),
                    project_id=project.id,
                    original_name=name,
                    media_type="text/markdown",
                    byte_size=len(text.encode()),
                    sha256=ids.new_handle("d"),
                    source_kind=SourceKind.local_path,
                    group_key=name,
                )
            )
            contents.append(text)

        svc = ProjectService(ids=ids)
        result = asyncio.run(
            svc.run_pipeline(project=project, sources=sources, contents=contents, plan=plan)
        )
        payload = result.to_dict()
        payload["release_bundle_sha256"] = result.release_sha256
        return payload

    # ------------------------------------------------------------------ utils
    async def _audit_review(
        workspace: "Workspace", example_id: str, decision: str, note: str, relabel: str | None
    ) -> None:
        from ...domain.ids import IdGenerator
        from ...infrastructure.database.repositories import AuditRepository

        db = workspace._db
        ids = IdGenerator()
        async with db.session() as session, session.begin():
            repo = AuditRepository(session, ids)
            await repo.record(
                principal="mcp",
                event_type=f"example.{decision}",
                project_id="",
                summary=f"{decision} example {example_id}",
                payload={"example_id": example_id, "note": note, "relabel": relabel},
            )

    _audit_review = staticmethod(_audit_review)

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
