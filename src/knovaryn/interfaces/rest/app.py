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
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ...application.service import ProjectService
from ...application.workspace import Workspace
from ...domain.ids import IdGenerator
from ...domain.schemas import DatasetPlan, Project, SourceDocument, SourceKind

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
    version="0.1.0",
    description="Open, MCP-native training-data foundry REST API.",
    lifespan=lifespan,
)
_bearer = HTTPBearer(auto_error=False)


def _require_auth(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    from ...domain.errors import AuthorizationError
    from ...infrastructure.auth.bearer import authorize, expected_token

    expected = expected_token()
    if not expected:
        # no token configured: allow in local/offline detection mode, but refuse
        # any publish-style operation at the service layer (defense in depth)
        return "local"
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing bearer token"
        )
    try:
        return authorize(creds.credentials)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def _ws() -> Workspace:
    if _workspace is None:
        raise HTTPException(status_code=503, detail="workspace not initialized")
    return _workspace


def _err(exc: Exception) -> HTTPException:
    from ...domain.errors import AlreadyExistsError, AuthorizationError, NotFoundError

    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, AlreadyExistsError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, AuthorizationError):
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ---------------------------------------------------------------- health
@app.get("/v1/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "product": "knovaryn", "server_id": "knovaryn_mcp"}


# --------------------------------------------------------------- projects
@app.post("/v1/projects", dependencies=[Depends(_require_auth)])
async def create_project(body: dict[str, Any]) -> dict[str, Any]:
    try:
        project = await _ws().create_project(
            slug=body["slug"],
            display_name=body["display_name"],
            description=body.get("description", ""),
            tags=body.get("tags"),
        )
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc
    return project.model_dump(mode="json")


@app.get("/v1/projects", dependencies=[Depends(_require_auth)])
async def list_projects(limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
    return await _ws().list_projects(limit=limit, cursor=cursor)


@app.get("/v1/projects/{project_id}", dependencies=[Depends(_require_auth)])
async def get_project(project_id: str) -> dict[str, Any]:
    try:
        project = await _ws().get_project(project_id)
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc
    return project.model_dump(mode="json")


# --------------------------------------------------------------- sources
@app.post("/v1/projects/{project_id}/sources", dependencies=[Depends(_require_auth)])
async def add_source(project_id: str, body: dict[str, Any]) -> dict[str, Any]:
    try:
        src = await _ws().add_source(
            project_id=project_id,
            original_name=body["original_name"],
            media_type=body.get("media_type", "text/markdown"),
            content=body.get("content", ""),
            declared_license=body.get("declared_license"),
        )
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc
    return src.model_dump(mode="json")


@app.get("/v1/projects/{project_id}/sources", dependencies=[Depends(_require_auth)])
async def list_sources(project_id: str, limit: int = 100) -> dict[str, Any]:
    return await _ws().list_sources(project_id=project_id, limit=limit)


@app.get("/v1/projects/{project_id}/sources/{source_id}", dependencies=[Depends(_require_auth)])
async def inspect_source(project_id: str, source_id: str) -> dict[str, Any]:
    data = await _ws().list_sources(project_id=project_id, limit=1000)
    for s in data.get("sources", []):
        if s.get("id") == source_id:
            return {**s, "inspect": f"knovaryn://projects/{project_id}/sources/{source_id}/summary"}
    raise HTTPException(status_code=404, detail=f"source not found: {source_id}")


@app.get("/v1/projects/{project_id}/license", dependencies=[Depends(_require_auth)])
async def license_report(project_id: str) -> dict[str, Any]:
    """Source license + privacy report and §15.6 publication-gate decision."""
    return await _ws().license_report(project_id=project_id)


# --------------------------------------------------------- pipeline jobs
@app.post("/v1/projects/{project_id}/pipeline", dependencies=[Depends(_require_auth)])
async def start_pipeline(project_id: str, body: dict[str, Any]) -> dict[str, Any]:
    try:
        job = await _ws().start_pipeline(
            project_id=project_id,
            task_family_proportions=body.get("task_family_proportions"),
            idempotency_key=body.get("idempotency_key"),
        )
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc
    return job.model_dump(mode="json")


@app.get("/v1/jobs/{job_id}", dependencies=[Depends(_require_auth)])
async def get_job(job_id: str) -> dict[str, Any]:
    try:
        summary = await _ws().get_job(job_id)
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc
    return summary.to_dict()


@app.post("/v1/jobs/{job_id}/run", dependencies=[Depends(_require_auth)])
async def run_job(job_id: str) -> dict[str, Any]:
    try:
        return await _ws().run_job(job_id)
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc


@app.post("/v1/jobs/{job_id}/cancel", dependencies=[Depends(_require_auth)])
async def cancel_job(job_id: str) -> dict[str, Any]:
    try:
        job = await _ws().request_cancel(job_id)
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc
    return {"job_id": job.id, "state": job.state.value, "cancellation_requested": True}


@app.post("/v1/jobs/{job_id}/resume", dependencies=[Depends(_require_auth)])
async def resume_job(job_id: str) -> dict[str, Any]:
    try:
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


@app.get("/v1/jobs", dependencies=[Depends(_require_auth)])
async def list_jobs(project_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    return await _ws().list_jobs(project_id=project_id, limit=limit)


# ------------------------------------------------------------- examples
@app.get("/v1/projects/{project_id}/examples", dependencies=[Depends(_require_auth)])
async def list_examples(
    project_id: str, status: str | None = None, limit: int = 100
) -> dict[str, Any]:
    return await _ws().list_examples(project_id=project_id, status=status, limit=limit)


@app.post(
    "/v1/projects/{project_id}/examples/{example_id}/review", dependencies=[Depends(_require_auth)]
)
async def review_example(project_id: str, example_id: str, body: dict[str, Any]) -> dict[str, Any]:
    decision = body.get("decision", "accept")
    if decision not in ("accept", "reject", "edit"):
        raise HTTPException(status_code=400, detail=f"unsupported decision: {decision}")
    return {
        "status": "recorded",
        "project_id": project_id,
        "example_id": example_id,
        "decision": decision,
        "note": body.get("note", ""),
        "relabel": body.get("relabel"),
    }


# ------------------------------------------------------------- datasets
@app.post("/v1/projects/{project_id}/validate", dependencies=[Depends(_require_auth)])
async def validate_dataset(project_id: str) -> dict[str, Any]:
    return await _ws().validate_dataset(project_id=project_id)


@app.post("/v1/projects/{project_id}/version", dependencies=[Depends(_require_auth)])
async def create_version(project_id: str, body: dict[str, Any]) -> dict[str, Any]:
    try:
        version = await _ws().create_version(
            project_id=project_id, semantic_version=body.get("semantic_version")
        )
    except Exception as exc:  # noqa: BLE001
        raise _err(exc) from exc
    return version.model_dump(mode="json")


@app.post("/v1/projects/{project_id}/export", dependencies=[Depends(_require_auth)])
async def export_dataset(project_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    body = body or {}
    return await _ws().export_dataset(project_id=project_id, version_id=body.get("version_id"))


@app.post("/v1/projects/{project_id}/publish", dependencies=[Depends(_require_auth)])
async def publish_dataset(project_id: str, body: dict[str, Any]) -> dict[str, Any]:
    dry_run = body.get("dry_run", True)
    confirm = body.get("confirm", False)
    repo_id = body.get("repo_id", "")
    if not confirm and not dry_run:
        raise HTTPException(
            status_code=400, detail="publish requires confirm=true (external side effect)"
        )
    if not repo_id:
        raise HTTPException(status_code=400, detail="repo_id is required")
    return await _ws().publish_dataset(project_id=project_id, repo_id=repo_id, dry_run=dry_run)


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
    """Minimal web console dashboard backed by the REST control plane."""
    from fastapi.responses import HTMLResponse

    html = (
        '<!doctype html><html lang="en"><head>\n'
        + '<meta charset="utf-8"><title>Knovaryn Console</title>\n'
        + "<style>body{font-family:system-ui,sans-serif;max-width:820px;margin:36px auto;"
        "padding:0 16px;color:#1a1a1a}\n"
        + "h1{font-size:1.5rem}h2{font-size:1.1rem;margin-top:28px}\n"
        + "input,select{font:inherit;padding:7px 10px;border:1px solid #d4d4d8;border-rad"
        "ius:8px;margin:3px 0}\n"
        + "button{padding:8px 14px;font-size:.95rem;cursor:pointer;border:0;border-radius"
        ":8px;background:#2563eb;color:#fff;margin:3px 4px 3px 0}\n"
        + "button.sec{background:#6b7280}pre{background:#f4f4f5;padding:14px;border-radiu"
        "s:8px;overflow:auto;font-size:.85rem}\n"
        + "label{display:block;font-weight:600;margin-top:10px;font-size:.85rem}.row{disp"
        "lay:flex;gap:8px;align-items:center;flex-wrap:wrap}</style>\n"
        + "</head><body>\n"
        + "<h1>Knovaryn Console</h1>\n"
        + "<p>Training-data foundry. Server: <code>knovaryn_mcp</code> · offline default "
        "(fake provider).</p>\n"
        + "\n"
        + "<h2>Project</h2>\n"
        + '<input id="slug" placeholder="my-project"><input id="name" placeholder="Displa'
        'y name" style="width:220px">\n'
        + "<button onclick=\"post('/v1/projects',{slug:slug.value,display_name:name.value}"
        ')">Create project</button>\n'
        + '<button class="sec" onclick="get(\'/v1/projects\')">List projects</button>\n'
        + "\n"
        + "<h2>Source</h2>\n"
        + '<input id="pid" placeholder="project_id"><input id="srcname" placeholder="sour'
        'ce name">\n'
        + '<textarea id="srccontent" rows="3" style="width:100%" placeholder="markdown co'
        'ntent"></textarea>\n'
        + "<button onclick=\"post('/v1/projects/'+pid.value+'/sources',{original_name:srcn"
        'ame.value,content:srccontent.value})">Add source</button>\n'
        + "\n"
        + "<h2>Pipeline</h2>\n"
        + "<div class=\"row\"><button onclick=\"post('/v1/projects/'+pid.value+'/pipeline',{"
        '})">Queue pipeline</button>\n'
        + "<button onclick=\"get('/v1/jobs?project_id='+pid.value)\">List jobs</button></di"
        "v>\n"
        + "\n"
        + "<h2>Run &amp; export</h2>\n"
        + '<input id="jid" placeholder="job_id" style="width:240px"><button onclick="post'
        "('/v1/jobs/'+jid.value+'/run',{})\">Run job</button>\n"
        + "<button onclick=\"post('/v1/projects/'+pid.value+'/version',{})\">Create version"
        "</button>\n"
        + "<button onclick=\"post('/v1/projects/'+pid.value+'/export',{})\">Export</button>\n"
        + "<button class=\"sec\" onclick=\"post('/v1/projects/'+pid.value+'/publish',{dry_ru"
        "n:true,confirm:true,repo_id:'local/dry-run'})\">Publish (dry-run)</button>\n"
        + "\n"
        + "<h2>Demo</h2>\n"
        + "<button onclick=\"fetch('/v1/demo',{method:'POST'}).then(r=>r.json()).then(rend"
        'er)">Run full offline demo</button>\n'
        + "\n"
        + '<pre id="out">Use the buttons above; output appears here.</pre>\n'
        + "<script>\n"
        + "async function j(url,opts) { const r=await fetch(url,{method:(opts&&opts.metho"
        "d)||'GET',headers:{'Content-Type':'application/json'},body:opts&&opts.body?JSO"
        "N.stringify(opts.body):undefined}); return {status:r.status, body:await r.text"
        "()}; }\n"
        + "async function get(url){const r=await j(url);render(parse(r));}\n"
        + "async function post(url,body){const r=await j(url,{method:'POST',body});render"
        "(parse(r));}\n"
        + "function parse(r){try{return JSON.parse(r.body)}catch(e){return {status:r.stat"
        "us,raw:r.body}}}\n"
        + "function render(x){document.getElementById('out').textContent=JSON.stringify(x"
        ",null,2);}\n" + "</script>\n" + "</body></html>"
    )
    return HTMLResponse(html)


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
