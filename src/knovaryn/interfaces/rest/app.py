"""Knovaryn REST API (spec §17.3).

Exposes project / pipeline / demo operations over HTTP with FastAPI. The offline
``/v1/demo`` endpoint runs the full pipeline with the fake provider and returns
a release bundle. Public endpoints are scoped behind a minimal bearer-token
guard so the server never publishes or exposes data without the operator's
authorization.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ...domain.ids import IdGenerator
from ...domain.schemas import DatasetPlan, Project, SourceDocument, SourceKind
from ...application.service import ProjectService

app = FastAPI(
    title="Knovaryn",
    version="0.1.0",
    description="Open, MCP-native training-data foundry REST API.",
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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing bearer token")
    try:
        return authorize(creds.credentials)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@app.get("/v1/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "product": "knovaryn", "server_id": "knovaryn_mcp"}


@app.get("/", include_in_schema=False)
def web_console() -> Any:
    """Minimal web console: a single dashboard page that renders the demo result."""
    from fastapi.responses import HTMLResponse

    html = """<!doctype html><html lang="en"><head>
<meta charset="utf-8"><title>Knovaryn Console</title>
<style>body{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 16px;color:#1a1a1a}
h1{font-size:1.6rem}pre{background:#f4f4f5;padding:16px;border-radius:8px;overflow:auto}
button{padding:10px 16px;font-size:1rem;cursor:pointer;border:0;border-radius:8px;background:#2563eb;color:#fff}</style>
</head><body>
<h1>Knovaryn Console</h1>
<p>Training-data foundry. Server: <code>knovaryn_mcp</code>.</p>
<button onclick="fetch('/v1/demo').then(r=>r.json()).then(j=>{document.getElementById('out').textContent=JSON.stringify(j,null,2)})">Run offline demo</button>
<pre id="out">Run the demo to see the pipeline result.</pre>
</body></html>"""
    return HTMLResponse(html)


@app.post("/v1/demo", dependencies=[Depends(_require_auth)])
async def run_demo() -> dict[str, Any]:
    """Run the offline end-to-end pipeline on bundled sample documents."""
    import asyncio

    ids = IdGenerator()
    project = Project(id=ids.new_handle("proj"), slug="demo", display_name="Knovaryn Demo", owner_principal="rest")
    plan = DatasetPlan(task_family_proportions={"factual_explanation": 0.5, "procedure": 0.3, "comparison": 0.2})
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
    result = await svc.run_pipeline(project=project, sources=sources, contents=contents, plan=plan)
    return result.to_dict()


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
## Deployment and monitoring
Once deployed, models require ongoing monitoring for drift. Concept drift occurs when the statistical properties of the input distribution change over time.
""",
    ),
]


def create_app() -> FastAPI:
    return app
