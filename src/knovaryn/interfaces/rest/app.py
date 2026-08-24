"""Knovaryn REST API (spec §17.3, control plane).

Exposes the full workspace control plane over HTTP with FastAPI:

* projects: create / list / get
* sources: add / list / inspect
* pipeline jobs: start / get / run / cancel / resume / list
* examples: preview / review
* datasets: validate / version / export / publish (dry-run)

The offline ``/v1/demo`` endpoint runs the full pipeline with the fake provider
and returns a bounded result. Public endpoints are scoped behind a minimal
bearer-token guard so the server never publishes or exposes data without the
operator's authorization. A single :class:`Workspace` is created at startup and
shared by all routes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, status

from ... import __version__
from ...application.service import ProjectService
from ...application.workspace import Workspace
from ...domain.ids import IdGenerator
from ...domain.schemas import DatasetPlan, Project, SourceDocument, SourceKind
from .schemas import (
    ExportRequest,
    PipelineStart,
    ProjectCreate,
    PublishRequest,
    ReviewRequest,
    SourceAdd,
    VersionCreate,
)
from .security import Principal, require_scope

# shared workspace instance (lazily opened on startup)
_workspace: Workspace | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _workspace
    workspace = Workspace(principal="rest")
    await workspace.open()
    _workspace = workspace
    yield
    await workspace.close()
    _workspace = None


app = FastAPI(
    title="Knovaryn",
    # authoritative version source (defect 3.5) — never a literal here
    version=__version__,
    description="Open, MCP-native training-data foundry REST API.",
    lifespan=lifespan,
)

# ---------------------------------------------------------- web security (J5)
from .rate_limit import RateLimitMiddleware  # noqa: E402
from .security_middleware import (  # noqa: E402
    BodyLimitMiddleware,
    SecurityHeadersMiddleware,
    redacted_exception_handler,
    restrict_cors,
)

# Order matters (inner-most declared last is applied first): rate limiting and
# body limit should run before security headers so budgeted/toobig requests never
# get a full response.
app.add_middleware(BodyLimitMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
restrict_cors(app, allowed_origins=None)  # no allowlist => deny all cross-origin
app.add_exception_handler(Exception, redacted_exception_handler)

# Scope-gated dependencies. Each route declares the scope it needs; a missing
# scope yields 403 (never a silent pass — rule 6). The returned Principal is
# threaded into the workspace so ownership/tenancy is enforced on the shared
# application-service path.
# Canonical scope names (spec §23.2) — defect 4.10 unified vocabulary.
P_PROJECT_READ = require_scope("projects:read")
P_PROJECT_WRITE = require_scope("projects:write")
P_SOURCE_WRITE = require_scope("sources:write")
P_JOB_RUN = require_scope("runs:execute")
P_REVIEW_WRITE = require_scope("review:write")
P_EXPORT_READ = require_scope("datasets:export")
P_PUBLISH_WRITE = require_scope("datasets:publish")
P_ADMIN = require_scope("admin")


def _require_auth(creds: str | None = None) -> str:
    """Legacy no-arg auth guard kept for the ``/v1/demo`` and health routes.

    Resolves the principal without requiring a specific scope (demo runs the
    local offline pipeline only).
    """
    from .security import resolve_principal

    try:
        return resolve_principal(creds).name
    except Exception as exc:  # noqa: BLE001 - AuthorizationError -> 401
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def _ws() -> Workspace:
    if _workspace is None:
        raise HTTPException(status_code=503, detail="workspace not initialized")
    return _workspace


def _err(exc: Exception) -> HTTPException:
    """Map domain errors to correct HTTP status codes (WP J2).

    Never echoes internal detail that could leak secrets or path layout; the
    ``detail`` is the public, redacted message only (J5 error redaction).
    """
    from ...domain import errors as E

    mapping: list[tuple[type[Exception], int]] = [
        (E.NotFoundError, status.HTTP_404_NOT_FOUND),
        # already exists / version conflict / job-state conflict: 409
        (E.AlreadyExistsError, status.HTTP_409_CONFLICT),
        (E.ConcurrencyError, status.HTTP_409_CONFLICT),
        (E.JobStateError, status.HTTP_409_CONFLICT),
        # authorization / policy block: 403 (never 200, rule 6)
        (E.AuthorizationError, status.HTTP_403_FORBIDDEN),
        (E.PolicyBlockError, status.HTTP_403_FORBIDDEN),
        (E.BudgetExceededError, status.HTTP_403_FORBIDDEN),
        (E.ProviderError, status.HTTP_502_BAD_GATEWAY),
        # a configured abuse-control budget is exhausted: 429 (J7)
        (E.RateLimitError, status.HTTP_429_TOO_MANY_REQUESTS),
        # payload too large / quarantine / unsafe intake: 413 / 422 / 400
        (E.ArchiveBombError, status.HTTP_413_CONTENT_TOO_LARGE),
        (E.PathTraversalError, status.HTTP_400_BAD_REQUEST),
        (E.SSRFError, status.HTTP_400_BAD_REQUEST),
        (E.MalwareScanError, status.HTTP_422_UNPROCESSABLE_CONTENT),
        (E.CorruptedArtifactError, status.HTTP_422_UNPROCESSABLE_CONTENT),
        (E.ValidationError, status.HTTP_422_UNPROCESSABLE_CONTENT),
        (E.ExportError, status.HTTP_422_UNPROCESSABLE_CONTENT),
        (E.IntakeError, status.HTTP_400_BAD_REQUEST),
    ]
    for cls, code in mapping:
        if isinstance(exc, cls):
            return HTTPException(status_code=code, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ---------------------------------------------------------------- health
@app.get("/v1/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "product": "knovaryn", "server_id": "knovaryn_mcp"}


# ----------------------------------------------------------- observability (K4)
@app.get("/v1/metrics", dependencies=[Depends(P_ADMIN)], include_in_schema=False)
def metrics_endpoint() -> Any:
    """Prometheus text exposition of process-level runtime metrics (spec §22.2)."""
    from fastapi.responses import PlainTextResponse

    from ...infrastructure.telemetry.metrics import get_registry

    return PlainTextResponse(get_registry().render_prometheus(), media_type="text/plain")


# --------------------------------------------------------------- projects
@app.post(
    "/v1/projects",
    status_code=201,
)
async def create_project(
    body: ProjectCreate, principal: Principal = Depends(P_PROJECT_WRITE)
) -> dict[str, Any]:
    try:
        project = await _ws().create_project(
            slug=body.slug,
            display_name=body.display_name,
            description=body.description,
            tags=body.tags,
            owner_principal=principal.name,
        )
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc
    return project.model_dump(mode="json")


@app.get("/v1/projects")
async def list_projects(
    limit: int = 50,
    cursor: str | None = None,
    principal: Principal = Depends(P_PROJECT_READ),
) -> dict[str, Any]:
    # owner-tenant isolation: non-admin principals only see projects they own
    return await _ws().list_projects_visible(principal=principal.name, limit=limit, cursor=cursor)


@app.get("/v1/projects/{project_id}")
async def get_project(
    project_id: str, principal: Principal = Depends(P_PROJECT_READ)
) -> dict[str, Any]:
    try:
        await _ws().require_project_access(
            project_id=project_id, principal=principal.name, scope="projects:read"
        )
        project = await _ws().get_project(project_id)
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc
    return project.model_dump(mode="json")


# --------------------------------------------------------------- sources
@app.post(
    "/v1/projects/{project_id}/sources",
    status_code=201,
)
async def add_source(
    project_id: str,
    body: SourceAdd,
    principal: Principal = Depends(P_SOURCE_WRITE),
) -> dict[str, Any]:
    try:
        await _ws().require_project_access(
            project_id=project_id, principal=principal.name, scope="sources:write"
        )
        src = await _ws().add_source(
            project_id=project_id,
            original_name=body.original_name,
            media_type=body.media_type or "text/markdown",
            content=body.content or "",
            raw=body.raw,
            declared_license=body.declared_license,
            privacy=body.privacy,
        )
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc
    return src.model_dump(mode="json")


@app.get("/v1/projects/{project_id}/sources")
async def list_sources(
    project_id: str,
    limit: int = 100,
    principal: Principal = Depends(P_PROJECT_READ),
) -> dict[str, Any]:
    try:
        await _ws().require_project_access(
            project_id=project_id, principal=principal.name, scope="projects:read"
        )
        return await _ws().list_sources(project_id=project_id, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


@app.get("/v1/projects/{project_id}/sources/{source_id}")
async def inspect_source(
    project_id: str,
    source_id: str,
    principal: Principal = Depends(P_PROJECT_READ),
) -> dict[str, Any]:
    try:
        await _ws().require_project_access(
            project_id=project_id, principal=principal.name, scope="projects:read"
        )
        data = await _ws().list_sources(project_id=project_id, limit=1000)
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc
    for s in data.get("sources", []):
        if s.get("id") == source_id:
            return {**s, "inspect": f"knovaryn://projects/{project_id}/sources/{source_id}/summary"}
    raise HTTPException(status_code=404, detail=f"source not found: {source_id}")


@app.get("/v1/projects/{project_id}/license")
async def license_report(
    project_id: str, principal: Principal = Depends(P_PROJECT_READ)
) -> dict[str, Any]:
    """Source license + privacy report and §15.6 publication-gate decision."""
    try:
        await _ws().require_project_access(
            project_id=project_id, principal=principal.name, scope="projects:read"
        )
        return await _ws().license_report(project_id=project_id)
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


# --------------------------------------------------------- pipeline jobs
@app.post(
    "/v1/projects/{project_id}/pipeline",
    status_code=202,
)
async def start_pipeline(
    project_id: str,
    body: PipelineStart,
    principal: Principal = Depends(P_JOB_RUN),
) -> dict[str, Any]:
    try:
        await _ws().require_project_access(
            project_id=project_id, principal=principal.name, scope="runs:execute"
        )
        job = await _ws().start_pipeline(
            project_id=project_id,
            task_family_proportions=body.task_family_proportions,
            idempotency_key=body.idempotency_key,
            profile=body.profile,
            budget_max_usd=body.budget_max_usd,
            target_examples=body.target_examples,
        )
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc
    return job.model_dump(mode="json")


async def _job_project_guard(job_id: str, principal: Principal, scope: str) -> None:
    """Authorize ``principal`` to act on the project that owns ``job``."""
    summary = await _ws().get_job(job_id)
    await _ws().require_project_access(
        project_id=summary.job.project_id, principal=principal.name, scope=scope
    )


@app.get("/v1/jobs/{job_id}")
async def get_job(job_id: str, principal: Principal = Depends(P_JOB_RUN)) -> dict[str, Any]:
    try:
        await _job_project_guard(job_id, principal, "runs:execute")
        summary = await _ws().get_job(job_id)
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc
    return summary.to_dict()


@app.post("/v1/jobs/{job_id}/run")
async def run_job(job_id: str, principal: Principal = Depends(P_JOB_RUN)) -> dict[str, Any]:
    try:
        await _job_project_guard(job_id, principal, "runs:execute")
        return await _ws().run_job(job_id)
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


@app.post("/v1/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, principal: Principal = Depends(P_JOB_RUN)) -> dict[str, Any]:
    try:
        await _job_project_guard(job_id, principal, "runs:execute")
        job = await _ws().request_cancel(job_id)
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc
    return {"job_id": job.id, "state": job.state.value, "cancellation_requested": True}


@app.post("/v1/jobs/{job_id}/resume")
async def resume_job(job_id: str, principal: Principal = Depends(P_JOB_RUN)) -> dict[str, Any]:
    try:
        await _job_project_guard(job_id, principal, "runs:execute")
        summary = await _ws().get_job(job_id)
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc
    if summary.job.state.value in ("failed", "cancelling", "succeeded"):
        return await _ws().run_job(job_id)
    return {
        "job_id": job_id,
        "state": summary.job.state.value,
        "message": "not in a resumable terminal state",
    }


@app.get("/v1/jobs")
async def list_jobs(
    project_id: str | None = None,
    limit: int = 50,
    principal: Principal = Depends(P_JOB_RUN),
) -> dict[str, Any]:
    try:
        if project_id:
            await _ws().require_project_access(
                project_id=project_id, principal=principal.name, scope="runs:execute"
            )
        return await _ws().list_jobs(project_id=project_id, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


# ------------------------------------------------------------- examples
@app.get("/v1/projects/{project_id}/examples")
async def list_examples(
    project_id: str,
    status: str | None = None,
    limit: int = 100,
    principal: Principal = Depends(P_EXPORT_READ),
) -> dict[str, Any]:
    try:
        await _ws().require_project_access(
            project_id=project_id, principal=principal.name, scope="datasets:export"
        )
        return await _ws().list_examples(project_id=project_id, status=status, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


@app.get("/v1/projects/{project_id}/examples/{example_id}/lineage")
async def get_example_lineage(
    project_id: str,
    example_id: str,
    principal: Principal = Depends(P_EXPORT_READ),
) -> dict[str, Any]:
    """Provenance + lineage for one example, including per-span location
    precision (defect 3.7) so provenance claims are machine-verifiable."""
    try:
        await _ws().require_project_access(
            project_id=project_id, principal=principal.name, scope="datasets:export"
        )
        data = await _ws().list_examples(project_id=project_id, limit=10000)
        match = next((e for e in data.get("examples", []) if e.get("id") == example_id), None)
        if match is None:
            from ...domain.errors import NotFoundError

            raise NotFoundError(f"example not found: {example_id}")
        span_ids = match.get("source_span_ids", [])
        locations = await _ws().get_span_locations(span_ids)
        return {
            "example_id": example_id,
            "project_id": project_id,
            "source_document_ids": match.get("source_document_ids", []),
            "source_group_ids": match.get("source_group_ids", []),
            "source_span_ids": span_ids,
            "source_spans": locations.get("spans", []),
            "chunk_id": match.get("chunk_id"),
            "topology": match.get("topology"),
        }
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


@app.post(
    "/v1/projects/{project_id}/examples/{example_id}/review",
    status_code=200,
)
async def review_example(
    project_id: str,
    example_id: str,
    body: ReviewRequest,
    principal: Principal = Depends(P_REVIEW_WRITE),
) -> dict[str, Any]:
    """Apply a review by appending an immutable revision (H1/H2/P0-9).

    Shares the single application-service path with the CLI/MCP/SDK — no
    interface-specific review logic. A stale ``concurrency_token`` / base
    ``revision_id`` returns ``409``.
    """
    try:
        await _ws().require_project_access(
            project_id=project_id, principal=principal.name, scope="review:write"
        )
        return await _ws().review_example(
            example_id=example_id,
            revision_id=body.revision_id or 1,
            reviewer=principal.name,
            decision=body.decision,
            note=body.note,
            policy_version=body.policy_version,
            concurrency_token=body.concurrency_token,
        )
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


# ------------------------------------------------------------- datasets
@app.post("/v1/projects/{project_id}/validate")
async def validate_dataset(
    project_id: str, principal: Principal = Depends(P_EXPORT_READ)
) -> dict[str, Any]:
    try:
        await _ws().require_project_access(
            project_id=project_id, principal=principal.name, scope="datasets:export"
        )
        return await _ws().validate_dataset(project_id=project_id)
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


@app.post(
    "/v1/projects/{project_id}/version",
    status_code=201,
)
async def create_version(
    project_id: str,
    body: VersionCreate,
    principal: Principal = Depends(P_EXPORT_READ),
) -> dict[str, Any]:
    try:
        await _ws().require_project_access(
            project_id=project_id, principal=principal.name, scope="datasets:export"
        )
        version = await _ws().create_version(
            project_id=project_id, semantic_version=body.semantic_version
        )
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc
    return version.model_dump(mode="json")


@app.post("/v1/projects/{project_id}/export")
async def export_dataset(
    project_id: str,
    body: ExportRequest,
    principal: Principal = Depends(P_EXPORT_READ),
) -> dict[str, Any]:
    try:
        await _ws().require_project_access(
            project_id=project_id, principal=principal.name, scope="datasets:export"
        )
        result = await _ws().export_dataset(project_id=project_id, version_id=body.version_id)
        # K4: export count (only a resolvable artifact counts — rule 13).
        from ...infrastructure.telemetry.metrics import get_registry

        fmt = str(getattr(body, "format", None) or "canonical-jsonl")
        get_registry().inc("knovaryn_export_total", labels={"format": fmt})
        return result
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


@app.post("/v1/projects/{project_id}/publish")
async def publish_dataset(
    project_id: str,
    body: PublishRequest,
    principal: Principal = Depends(P_PUBLISH_WRITE),
) -> dict[str, Any]:
    try:
        await _ws().require_project_access(
            project_id=project_id, principal=principal.name, scope="datasets:publish"
        )
        if not body.confirm and not body.dry_run:
            raise HTTPException(
                status_code=400, detail="publish requires confirm=true (external side effect)"
            )
        return await _ws().publish_dataset(
            project_id=project_id,
            repo_id=body.repo_id,
            dry_run=body.dry_run,
            principal=principal.name,
        )
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


# ------------------------------------------------------------------ demo
@app.post("/v1/demo", dependencies=[Depends(_require_auth)])
async def run_demo() -> dict[str, Any]:
    """Run the offline end-to-end pipeline on bundled sample documents."""
    ids = IdGenerator()
    project = Project(
        id=ids.new_handle("proj"), slug="demo", display_name="Knovaryn Demo", owner_principal="rest"
    )
    plan = DatasetPlan(
        task_family_proportions={"factual_explanation": 0.5, "procedure": 0.3, "comparison": 0.2}
    )
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
    result = await svc.run_pipeline(project=project, sources=sources, contents=contents, plan=plan)
    return result.to_dict()


# ------------------------------------------------------------------ console
@app.get("/", include_in_schema=False)
def web_console() -> Any:
    """Accessible web console backed by the REST control plane (spec §17.4, WP J6)."""
    from fastapi.responses import HTMLResponse

    from .webconsole import render_console

    return HTMLResponse(render_console())


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
## Deployment and monitoring
Once deployed, models require ongoing monitoring for drift. Concept drift occurs
when the statistical properties of the input distribution change over time.
""",
    ),
]


def create_app() -> FastAPI:
    return app
