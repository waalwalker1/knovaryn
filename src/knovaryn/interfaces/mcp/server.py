"""Knovaryn MCP server (spec §17, WP F).

Exposes the full WP F tool catalogue + resources on top of the framework-free
:class:`Workspace`. In line with WP F2, every tool and resource handler is a
*native async* function sharing a :class:`Workspace` that the server's lifespan
opens on startup and disposes on shutdown — there are no ``asyncio.run()``
bridges inside handlers.

The canonical server identity is ``knovaryn_mcp``. Requires the ``mcp`` package
(extra). All workspace operations run offline/deterministically with the fake
provider by default and need no credentials.
"""

from __future__ import annotations

import importlib.util
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

from ...domain.errors import ConfigurationError, NotFoundError

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context

    from ...application.workspace import Workspace
else:
    # FastMCP inspects tool signatures with ``eval_str=True``, so ``Context``
    # and ``Workspace`` must be real, resolvable names in this module's
    # namespace at runtime — a TYPE_CHECKING-only import is not enough
    # (FastMCP ``eval_str`` evaluates annotations against the module globals).
    # Import them for real when mcp is installed; ``Workspace`` is our own
    # module and always importable. If mcp is absent, fall back to a placeholder
    # so the module still imports for callers that only want ``SERVER_ID`` or
    # the availability flag.
    try:
        from mcp.server.fastmcp import Context
    except ImportError:  # pragma: no cover - mcp unavailable
        from typing import Any as Context  # type: ignore[assignment]

    from ...application.workspace import Workspace

SERVER_ID = "knovaryn_mcp"


def _mcp_available() -> bool:
    return importlib.util.find_spec("mcp") is not None


def _get_workspace(ctx: Context) -> Workspace:
    """Resolve the lifespan-managed workspace from a tool/resource context."""
    ws = ctx.request_context.lifespan_context
    if ws is None:
        raise ConfigurationError("MCP lifespan has not opened the workspace")
    return cast(Workspace, ws)


def _denied(msg: str = "resource not found or not accessible") -> dict[str, Any]:
    """Authorization/not-found denial shape (WP F5: enforce on every handle)."""
    return {"status": "error", "error": msg, "authorized": False}


def build_server(database_url: str | None = None) -> Any:
    """Construct the MCP fast server. Raises if ``mcp`` is not installed."""
    if not _mcp_available():
        raise ConfigurationError(
            "The MCP server requires the 'mcp' package. Install it (e.g. pip install mcp) "
            "or run Knovaryn via the CLI/REST instead."
        )
    from mcp.server.fastmcp import FastMCP

    from ...application.workspace import Workspace

    @asynccontextmanager
    async def _lifespan(mcp_server: FastMCP[Workspace]) -> AsyncIterator[Workspace]:
        ws = Workspace(principal="mcp", database_url=database_url)
        await ws.open()
        try:
            yield ws
        finally:
            await ws.close()

    mcp = FastMCP[Workspace](
        "Knovaryn",
        instructions="Training-data foundry pipeline tools.",
        lifespan=_lifespan,
    )

    # ------------------------------------------------------------------ misc
    @mcp.tool()
    async def health(ctx: Context) -> dict[str, Any]:
        """Health / identity check for the Knovaryn MCP server."""
        _get_workspace(ctx)  # fail closed if the lifespan workspace is not open
        return {"status": "ok", "server_id": SERVER_ID, "product": "knovaryn"}

    @mcp.tool()
    async def knovaryn_doctor() -> dict[str, Any]:
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
    async def knovaryn_create_project(
        ctx: Context,
        slug: str,
        display_name: str,
        description: str = "",
        owner_principal: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a project. Returns project_id, default profile, and actions."""
        ws = _get_workspace(ctx)
        try:
            project = await ws.create_project(
                slug=slug,
                display_name=display_name,
                description=description,
                owner_principal=owner_principal,
                tags=tags,
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
    async def knovaryn_list_projects(
        ctx: Context, limit: int = 50, cursor: str | None = None
    ) -> dict[str, Any]:
        """Paginated, filtered project summary."""
        ws = _get_workspace(ctx)
        return await ws.list_projects(limit=limit, cursor=cursor)

    # --------------------------------------------------------------- sources
    @mcp.tool()
    async def knovaryn_add_source(
        ctx: Context,
        project_id: str,
        original_name: str,
        content: str,
        media_type: str = "text/markdown",
        declared_license: str | None = None,
    ) -> dict[str, Any]:
        """Register an uploaded artifact. Returns source_id + next job handle."""
        from ...domain.schemas import SourceKind

        ws = _get_workspace(ctx)
        try:
            src = await ws.add_source(
                project_id=project_id,
                original_name=original_name,
                media_type=media_type,
                content=content,
                declared_license=declared_license,
                source_kind=SourceKind.upload,
            )
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}
        return {"status": "ok", "source_id": src.id, "next": "knovaryn_start_pipeline"}

    @mcp.tool()
    async def knovaryn_inspect_source(
        ctx: Context, project_id: str, source_id: str
    ) -> dict[str, Any]:
        """Metadata, preflight, extraction summary, license/privacy state."""
        ws = _get_workspace(ctx)
        sources = await ws.list_sources(project_id=project_id, limit=1000)
        for s in sources.get("sources", []):
            if s.get("id") == source_id:
                report = await ws.license_report(project_id=project_id)
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
    async def knovaryn_license_report(ctx: Context, project_id: str) -> dict[str, Any]:
        """Source license + privacy report and §15.6 publication-gate decision."""
        ws = _get_workspace(ctx)
        return await ws.license_report(project_id=project_id)

    # -------------------------------------------------------------- pipeline
    @mcp.tool()
    async def knovaryn_estimate_run(
        ctx: Context,
        project_id: str,
        target_count: int = 100,
        topology: str = "sft",
        task_families: str = "factual_explanation:0.5,procedure:0.3,comparison:0.2",
    ) -> dict[str, Any]:
        """Dry-run estimate for selected sources/topology/profile/targets."""
        from ...domain.policies import approximate_tokens

        ws = _get_workspace(ctx)
        sources = await ws.list_sources(project_id=project_id, limit=1000)
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
    async def knovaryn_start_pipeline(
        ctx: Context,
        project_id: str,
        task_fam_families: str = "factual_explanation:0.5,procedure:0.3,comparison:0.2",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Start a durable pipeline job (offline). Returns a job handle."""
        ws = _get_workspace(ctx)
        proportions: dict[str, float] = {}
        for pair in task_fam_families.split(","):
            if ":" in pair:
                fam, w = pair.split(":", 1)
                proportions[fam.strip()] = float(w.strip())
        if not proportions:
            proportions = {"factual_explanation": 1.0}
        try:
            job = await ws.start_pipeline(
                project_id=project_id,
                task_family_proportions=proportions,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}
        return {
            "job_id": job.id,
            "state": job.state.value,
            "job_type": job.job_type,
            "message": (
                "job queued — run knovaryn_get_job to poll, "
                "then knovaryn_run_job to execute offline"
            ),
        }

    @mcp.tool()
    async def knovaryn_get_job(ctx: Context, job_id: str) -> dict[str, Any]:
        """State, stage, progress, counts, costs, warnings, errors, events."""
        ws = _get_workspace(ctx)
        try:
            summary = await ws.get_job(job_id)
        except NotFoundError as exc:
            return _denied(str(exc))
        data = summary.to_dict()
        data["resources"] = {
            "job": f"knovaryn://projects/{summary.job.project_id}/jobs/{job_id}",
            "events": f"knovaryn://projects/{summary.job.project_id}/jobs/{job_id}/events",
        }
        return data

    @mcp.tool()
    async def knovaryn_list_jobs(
        ctx: Context, project_id: str | None = None, limit: int = 50, cursor: str | None = None
    ) -> dict[str, Any]:
        """Paginated job list (optionally filtered by project)."""
        ws = _get_workspace(ctx)
        data = await ws.list_jobs(project_id=project_id, limit=limit)
        for j in data.get("jobs", []):
            j["job_uri"] = f"knovaryn://projects/{j.get('project_id', '')}/jobs/{j.get('id', '')}"
        return data

    @mcp.tool()
    async def knovaryn_run_job(ctx: Context, job_id: str) -> dict[str, Any]:
        """Execute a queued pipeline job offline in-process (returns final state).

        This is the local worker that actually runs the pipeline. In a real
        deployment a separate worker/lease would claim and run the job; here it
        runs synchronously for the offline path.
        """
        ws = _get_workspace(ctx)
        try:
            return await ws.run_job(job_id)
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}

    @mcp.tool()
    async def knovaryn_cancel_job(ctx: Context, job_id: str) -> dict[str, Any]:
        """Request cooperative cancellation (idempotent)."""
        ws = _get_workspace(ctx)
        try:
            job = await ws.request_cancel(job_id)
            return {"job_id": job.id, "state": job.state.value, "cancellation_requested": True}
        except NotFoundError as exc:
            return _denied(str(exc))
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}

    @mcp.tool()
    async def knovaryn_resume_job(ctx: Context, job_id: str) -> dict[str, Any]:
        """Resume a retryable failed/paused job (re-lease and continue)."""
        ws = _get_workspace(ctx)
        try:
            summary = await ws.get_job(job_id)
            job_state = summary.job.state.value
        except NotFoundError as exc:
            return _denied(str(exc))
        if job_state in ("failed", "cancelling", "succeeded"):
            # re-queue and run again (idempotent replay of a retryable job)
            return await ws.run_job(job_id)
        if job_state == "paused":
            return {"job_id": job_id, "state": job_state, "message": "resume_job re-queues"}
        return {
            "job_id": job_id,
            "state": job_state,
            "message": "not in a resumable terminal state",
        }

    # ------------------------------------------------------------ examples
    @mcp.tool()
    async def knovaryn_preview_examples(
        ctx: Context, project_id: str, limit: int = 20, status: str | None = None
    ) -> dict[str, Any]:
        """Bounded, redacted page of examples + quality dimensions + evidence."""
        ws = _get_workspace(ctx)
        data = await ws.list_examples(project_id=project_id, status=status, limit=limit)
        for e in data.get("examples", []):
            e.pop("content", None)
            e["_redacted"] = True
        return data

    @mcp.tool()
    async def knovaryn_lineage(ctx: Context, project_id: str, example_id: str) -> dict[str, Any]:
        """Provenance + lineage for an example (source docs, spans, chunks)."""
        ws = _get_workspace(ctx)
        data = await ws.list_examples(project_id=project_id, limit=10000)
        for e in data.get("examples", []):
            if e.get("id") == example_id:
                return {
                    "example_id": example_id,
                    "project_id": project_id,
                    "source_document_ids": e.get("source_document_ids", []),
                    "source_group_ids": e.get("source_group_ids", []),
                    "source_span_ids": e.get("source_span_ids", []),
                    "chunk_id": e.get("chunk_id"),
                    "topology": e.get("topology"),
                    "lineage_uri": (
                        f"knovaryn://projects/{project_id}/examples/{example_id}/lineage"
                    ),
                }
        return _denied(f"example not found: {example_id}")

    @mcp.tool()
    async def knovaryn_review_example(
        ctx: Context,
        example_id: str,
        decision: str,
        note: str = "",
        relabel: str | None = None,
    ) -> dict[str, Any]:
        """Accept/reject/relabel an example (records an audit-trail decision)."""
        if decision not in ("accept", "reject", "edit"):
            return {"status": "error", "error": f"unsupported decision: {decision}"}
        ws = _get_workspace(ctx)
        try:
            await _audit_review(ws, example_id, decision, note, relabel)
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
    async def knovaryn_validate_dataset(
        ctx: Context, project_id: str, limit: int = 500
    ) -> dict[str, Any]:
        """Run validation for a project's examples; returns a bounded report."""
        ws = _get_workspace(ctx)
        return await ws.validate_dataset(project_id=project_id, limit=limit)

    @mcp.tool()
    async def knovaryn_create_dataset_version(
        ctx: Context, project_id: str, semantic_version: str | None = None
    ) -> dict[str, Any]:
        """Assemble an immutable draft version from accepted examples."""
        ws = _get_workspace(ctx)
        version = await ws.create_version(project_id=project_id, semantic_version=semantic_version)
        return {
            "version_id": version.id,
            "semantic_version": version.semantic_version,
            "train": version.train_count,
            "validation": version.validation_count,
            "test": version.test_count,
        }

    @mcp.tool()
    async def knovaryn_export_dataset(
        ctx: Context, project_id: str, version_id: str | None = None
    ) -> dict[str, Any]:
        """Export accepted examples as JSONL; returns artifact handles/summary."""
        ws = _get_workspace(ctx)
        res = await ws.export_dataset(project_id=project_id, version_id=version_id)
        res["artifact"] = f"knovaryn://projects/{project_id}/datasets/export/jsonl"
        return res

    @mcp.tool()
    async def knovaryn_publish_dataset(
        ctx: Context,
        project_id: str,
        repo_id: str,
        dry_run: bool = True,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Publish an approved version (external side effect). Dry-run by default."""
        ws = _get_workspace(ctx)
        if not dry_run and not confirm:
            return {
                "status": "error",
                "error": "publish requires confirm=true (external side effect)",
            }
        return await ws.publish_dataset(project_id=project_id, repo_id=repo_id, dry_run=dry_run)

    @mcp.tool()
    async def knovaryn_compare_runs(
        ctx: Context, project_id: str, job_id_a: str, job_id_b: str
    ) -> dict[str, Any]:
        """Compare quality/cost across two compatible runs."""
        ws = _get_workspace(ctx)
        a = (await ws.get_job(job_id_a)).to_dict()
        b = (await ws.get_job(job_id_b)).to_dict()
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
    async def run_pipeline(
        task_families: str = "factual_explanation:0.5,procedure:0.3,comparison:0.2",
    ) -> dict[str, Any]:
        """Run the offline end-to-end pipeline on bundled sample documents."""
        from ...application.service import ProjectService
        from ...domain.ids import IdGenerator
        from ...domain.schemas import DatasetPlan, Project, SourceDocument, SourceKind

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
        result = await svc.run_pipeline(
            project=project, sources=sources, contents=contents, plan=plan
        )
        payload = result.to_dict()
        payload["release_bundle_sha256"] = result.release_sha256
        return payload

    # ----------------------------------------------------------------- resources
    @mcp.resource("knovaryn://projects/{project_id}")
    async def project_resource(ctx: Context, project_id: str) -> dict[str, Any]:
        """Bounded project summary resource (authorized: must resolve)."""
        ws = _get_workspace(ctx)
        data = await ws.list_projects(limit=1000)
        for p in data.get("projects", []):
            if p.get("id") == project_id:
                return {"project_id": project_id, **p}
        return _denied(f"project not found: {project_id}")

    @mcp.resource("knovaryn://projects/{project_id}/jobs/{job_id}")
    async def job_resource(ctx: Context, project_id: str, job_id: str) -> dict[str, Any]:
        """Bounded job resource (authorization enforced on resolve)."""
        ws = _get_workspace(ctx)
        try:
            summary = await ws.get_job(job_id)
        except NotFoundError:
            return _denied(f"job not found: {job_id}")
        job = summary.job
        if job.project_id != project_id:
            return _denied("job does not belong to the requested project")
        data = summary.to_dict()
        data.pop("events", None)  # bounded: events live on their own resource
        return data

    @mcp.resource("knovaryn://projects/{project_id}/jobs/{job_id}/events")
    async def job_events_resource(ctx: Context, project_id: str, job_id: str) -> dict[str, Any]:
        """Bounded job events resource (capped to the latest N events)."""
        ws = _get_workspace(ctx)
        try:
            summary = await ws.get_job(job_id)
        except NotFoundError:
            return _denied(f"job not found: {job_id}")
        if summary.job.project_id != project_id:
            return _denied("job does not belong to the requested project")
        return {
            "job_id": job_id,
            "project_id": project_id,
            "event_count": len(summary.events),
            "events": summary.events[-200:],
        }

    @mcp.resource("knovaryn://projects/{project_id}/sources/{source_id}")
    async def source_resource(ctx: Context, project_id: str, source_id: str) -> dict[str, Any]:
        """Bounded source metadata resource (never raw content)."""
        ws = _get_workspace(ctx)
        sources = await ws.list_sources(project_id=project_id, limit=1000)
        for s in sources.get("sources", []):
            if s.get("id") == source_id:
                meta = dict(s)
                meta.pop("content", None)
                return meta
        return _denied(f"source not found: {source_id}")

    @mcp.resource("knovaryn://projects/{project_id}/examples/{example_id}/lineage")
    async def example_lineage_resource(
        ctx: Context, project_id: str, example_id: str
    ) -> dict[str, Any]:
        """Bounded example lineage resource."""
        ws = _get_workspace(ctx)
        data = await ws.list_examples(project_id=project_id, limit=10000)
        for e in data.get("examples", []):
            if e.get("id") == example_id:
                return {
                    "example_id": example_id,
                    "project_id": project_id,
                    "source_document_ids": e.get("source_document_ids", []),
                    "source_group_ids": e.get("source_group_ids", []),
                    "source_span_ids": e.get("source_span_ids", []),
                    "chunk_id": e.get("chunk_id"),
                    "topology": e.get("topology"),
                }
        return _denied(f"example not found: {example_id}")

    @mcp.resource("knovaryn://projects/{project_id}/datasets/{version_id}")
    async def dataset_resource(ctx: Context, project_id: str, version_id: str) -> dict[str, Any]:
        """Bounded dataset version resource (metadata, not blob bytes)."""
        from ...infrastructure.database.repositories import VersionRepository

        ws = _get_workspace(ctx)
        db = ws._db
        async with db.session() as session:
            version = await VersionRepository(session).get(version_id)
            if version is None:
                return _denied(f"dataset version not found: {version_id}")
            if version.project_id != project_id:
                return _denied("dataset version does not belong to the requested project")
            return {
                "version_id": version.id,
                "project_id": version.project_id,
                "semantic_version": version.semantic_version,
                "parent_version_id": version.parent_version_id,
                "train_count": version.train_count,
                "validation_count": version.validation_count,
                "test_count": version.test_count,
                "content_hash": version.content_hash,
            }

    # ------------------------------------------------------------------ utils
    return mcp


async def _audit_review(
    workspace: Workspace, example_id: str, decision: str, note: str, relabel: str | None
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


_DEMO_SOURCES = [
    (
        "MLOps lifecycle overview",
        """# MLOps Lifecycle
## Data preparation
Data preparation is the first step of any machine learning project. It involves
collecting raw data, cleaning it, and transforming it into a usable format.
Practitioners must document the provenance of every data source to keep the
dataset auditable.
## Model training
Model training consumes the prepared data. The training process optimizes model
weights against a loss function. Hyperparameters such as the learning rate and
batch size materially affect the final model quality.
## Evaluation
Evaluation measures model performance on held-out data. A held-out test set must
never be used to tune hyperparameters.
""",
    ),
    (
        "Incident response runbook",
        """# Incident Response Runbook
## Triage
Upon receiving an alert, the on-call engineer first confirms the alert is genuine
and not a false positive. The engineer classifies severity as low, medium, high,
or critical.
## Containment
Containment isolates the affected component to prevent further damage. For a
compromised service, this may mean rotating credentials and removing network
egress.
## Recovery
Recovery restores service from a known-good backup. The team verifies data
integrity before declaring recovery complete.
""",
    ),
]
