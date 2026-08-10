"""REST control-plane tests (spec §17.3).

Exercises the FastAPI app routes over the shared workspace: create project →
add source → queue + run pipeline → export. Runs offline with the fake provider.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from knovaryn.interfaces.rest.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Point the workspace at a throwaway sqlite file so tests don't touch the
    # repo's .knovaryn state or collide across runs.
    import knovaryn.application.workspace as ws_mod
    import knovaryn.interfaces.rest.app as rest_app

    db_url = f"sqlite+aiosqlite:///{tmp_path}/rest.db"

    def _fake_load_config():
        return {"storage.database_url": db_url}

    # The Workspace ctor reads cfg = load_config() -> storage.database_url.
    monkeypatch.setattr(ws_mod, "load_config", _fake_load_config)
    rest_app._workspace = None
    with TestClient(app) as c:
        yield c
    rest_app._workspace = None


def test_health(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_full_rest_lifecycle(client):
    # create project
    r = client.post("/v1/projects", json={"slug": "rest-widgets", "display_name": "Rest Widgets"})
    assert r.status_code == 200, r.text
    proj = r.json()
    assert proj["id"].startswith("proj_")

    # add source
    CONTENT = (
        "# Widgets\n## Assembly\n"
        "The widget is assembled from a base plate and a lid. The lid must be torqued to 5 N·m. "
        "Assembly takes about three minutes per unit.\n## Inspection\n"
        "Each unit is inspected for cracks before it ships. Units with visible "
        "defects are quarantined and reworked.\n"
    )
    r = client.post(
        f"/v1/projects/{proj['id']}/sources",
        json={"original_name": "a.md", "media_type": "text/markdown", "content": CONTENT},
    )
    assert r.status_code == 200, r.text
    src = r.json()
    assert src["id"].startswith("src_")

    # queue pipeline
    r = client.post(
        f"/v1/projects/{proj['id']}/pipeline",
        json={"task_family_proportions": {"factual_explanation": 1.0}},
    )
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["id"].startswith("job_")

    # run
    r = client.post(f"/v1/jobs/{job['id']}/run")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "succeeded"

    # get job
    r = client.get(f"/v1/jobs/{job['id']}")
    assert r.status_code == 200
    assert r.json()["state"] == "succeeded"

    # list examples
    r = client.get(f"/v1/projects/{proj['id']}/examples")
    assert r.status_code == 200
    assert len(r.json()["examples"]) > 0

    # export
    r = client.post(f"/v1/projects/{proj['id']}/export", json={})
    assert r.status_code == 200, r.text
    assert r.json()["sha256"]

    # publish dry-run (no hub installed => unavailable is acceptable)
    r = client.post(
        f"/v1/projects/{proj['id']}/publish",
        json={"repo_id": "local/w", "dry_run": True, "confirm": True},
    )
    assert r.status_code == 200
    assert r.json()["status"] in ("dry_run", "unavailable")


def test_rest_requires_repo_for_publish(client):
    proj = client.post("/v1/projects", json={"slug": "p2", "display_name": "P2"}).json()
    r = client.post(f"/v1/projects/{proj['id']}/publish", json={"dry_run": True, "confirm": True})
    assert r.status_code == 400
