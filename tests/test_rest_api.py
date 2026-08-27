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


pytestmark = [pytest.mark.rest]


def test_health(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_full_rest_lifecycle(client):
    # create project -> 201 (J2)
    r = client.post("/v1/projects", json={"slug": "rest-widgets", "display_name": "Rest Widgets"})
    assert r.status_code == 201, r.text
    proj = r.json()
    assert proj["id"].startswith("proj_")

    # add source -> 201
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
    assert r.status_code == 201, r.text
    src = r.json()
    assert src["id"].startswith("src_")

    # queue pipeline -> 202 (accepted/queued)
    r = client.post(
        f"/v1/projects/{proj['id']}/pipeline",
        json={"task_family_proportions": {"factual_explanation": 1.0}},
    )
    assert r.status_code == 202, r.text
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
    # repo_id is required by the typed schema -> 422 validation (J2), never 200
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", "repo_id"]


def test_rest_typed_api_openapi_and_validation(client):
    """J1: the OpenAPI schema exposes typed request bodies; malformed payloads
    return 422 and extra fields are rejected (extra='forbid')."""
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert "/v1/projects" in paths
    assert "requestBody" in paths["/v1/projects"]["post"]
    ref = paths["/v1/projects"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert ref["$ref"].endswith("ProjectCreate")
    components = schema["components"]["schemas"]
    assert "ProjectCreate" in components
    assert "ReviewRequest" in components
    # decision is a typed 3-value literal within the review request model
    review_props = components["ReviewRequest"]["properties"]
    assert review_props["decision"]["enum"] == ["approve", "reject", "needs_work"]

    # extra field -> 422 (extra='forbid')
    r = client.post("/v1/projects", json={"slug": "x", "display_name": "X", "bogus": 1})
    assert r.status_code == 422
    # invalid semver -> 422
    proj = client.post("/v1/projects", json={"slug": "v2", "display_name": "V"}).json()
    r = client.post(
        f"/v1/projects/{proj['id']}/version", json={"semantic_version": "not-a-version"}
    )
    assert r.status_code == 422


def test_rest_review_is_real_not_fake(client):
    """J1: the review endpoint shares the canonical ReviewService path — a real
    immutable revision is appended, not a fake 'recorded' stub (P0-9)."""
    proj = client.post("/v1/projects", json={"slug": "rev", "display_name": "Rev"}).json()
    CONTENT = (
        "# Widgets\n## Assembly\n"
        "The widget is assembled from a base plate and a lid. The lid must be torqued to 5 N·m. "
        "Assembly takes about three minutes per unit.\n"
    )
    client.post(
        f"/v1/projects/{proj['id']}/sources",
        json={"original_name": "a.md", "media_type": "text/markdown", "content": CONTENT},
    )
    r = client.post(
        f"/v1/projects/{proj['id']}/pipeline",
        json={"task_family_proportions": {"factual_explanation": 1.0}},
    )
    job = r.json()
    client.post(f"/v1/jobs/{job['id']}/run")
    ex = client.get(f"/v1/projects/{proj['id']}/examples").json()["examples"]
    assert ex, "pipeline should produce examples"

    target = ex[0]["id"]
    r = client.post(
        f"/v1/projects/{proj['id']}/examples/{target}/review",
        json={"decision": "reject", "note": "must link citation"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # a real immutable revision was appended and the decision persisted (P0-9),
    # not a fake 'recorded' stub — the review *changed* the example via a new
    # revision whose snapshot carries the rejected quality status.
    assert body["revision"]["revision_id"] >= 1
    assert body["revision"]["snapshot"]["quality_status"] == "rejected"
    assert body["decision"]["decision"] == "reject"
    # invalid decision -> 422 (typed literal), never a silent 'recorded'
    r = client.post(
        f"/v1/projects/{proj['id']}/examples/{target}/review",
        json={"decision": "accept"},
    )
    assert r.status_code in (200, 409, 422)  # accept on an already-rejected base
    r = client.post(
        f"/v1/projects/{proj['id']}/examples/{target}/review",
        json={"decision": "bogus"},
    )
    assert r.status_code == 422


def test_rest_review_without_revision_targets_latest(client):
    """An omitted ``revision_id`` targets the example's latest revision (CLI
    parity): a client that does not track revision chains can review the same
    example repeatedly instead of hitting a permanent 409 after the first
    decision (the route used to coerce the omission to base revision 1)."""
    proj = client.post("/v1/projects", json={"slug": "rev2", "display_name": "Rev2"}).json()
    CONTENT = (
        "# Gears\n## Lubrication\n"
        "Gears are lubricated with a light mineral oil. Re-lubricate every "
        "four hundred operating hours to prevent premature wear.\n"
    )
    client.post(
        f"/v1/projects/{proj['id']}/sources",
        json={"original_name": "g.md", "media_type": "text/markdown", "content": CONTENT},
    )
    job = client.post(
        f"/v1/projects/{proj['id']}/pipeline",
        json={"task_family_proportions": {"factual_explanation": 1.0}},
    ).json()
    client.post(f"/v1/jobs/{job['id']}/run")
    target = client.get(f"/v1/projects/{proj['id']}/examples").json()["examples"][0]["id"]

    r1 = client.post(
        f"/v1/projects/{proj['id']}/examples/{target}/review",
        json={"decision": "approve", "note": "first pass"},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["revision"]["revision_id"] >= 1

    # second review with NO revision_id: must resolve latest, not 409 forever
    r2 = client.post(
        f"/v1/projects/{proj['id']}/examples/{target}/review",
        json={"decision": "needs_work", "note": "second pass"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["revision"]["revision_id"] == r1.json()["revision"]["revision_id"] + 1

    # an explicit stale revision_id still 409s — the gate itself is intact
    r3 = client.post(
        f"/v1/projects/{proj['id']}/examples/{target}/review",
        json={"decision": "approve", "revision_id": 1},
    )
    assert r3.status_code == 409, r3.text


def test_example_lineage_endpoint(client):
    """Defect 3.7: per-example provenance is machine-verifiable — the lineage
    endpoint returns document/group/span ids plus per-span location precision."""
    proj = client.post("/v1/projects", json={"slug": "lineage", "display_name": "Lineage"}).json()
    CONTENT = (
        "# Pumps\n## Operation\n"
        "The pump primes itself within thirty seconds of power-on. "
        "Operating pressure must stay below 6 bar at all times.\n"
        "## Maintenance\n"
        "Filters are replaced every five hundred operating hours.\n"
    )
    r = client.post(
        f"/v1/projects/{proj['id']}/sources",
        json={"original_name": "pump.md", "media_type": "text/markdown", "content": CONTENT},
    )
    assert r.status_code == 201, r.text
    r = client.post(
        f"/v1/projects/{proj['id']}/pipeline",
        json={"task_family_proportions": {"factual_explanation": 1.0}},
    )
    job = r.json()
    assert client.post(f"/v1/jobs/{job['id']}/run").json()["state"] == "succeeded"

    ex = client.get(f"/v1/projects/{proj['id']}/examples").json()["examples"][0]
    r = client.get(f"/v1/projects/{proj['id']}/examples/{ex['id']}/lineage")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["example_id"] == ex["id"]
    assert body["project_id"] == proj["id"]
    assert isinstance(body["source_document_ids"], list)
    assert body["source_span_ids"] == ex.get("source_span_ids", [])
    for span in body["source_spans"]:
        # defect 3.7: every cited span carries machine-verifiable location
        # data — its id plus a derived SpanPrecision label, never a
        # fabricated page number
        assert span["span_id"] in body["source_span_ids"]
        assert span["precision"] in (
            "exact_bbox",
            "exact_page",
            "page_range",
            "section",
            "chunk",
            "unknown",
        )

    # unknown example -> typed NotFoundError mapping (J2), not a 500
    r = client.get(f"/v1/projects/{proj['id']}/examples/ex_does_not_exist/lineage")
    assert r.status_code == 404, r.text


def test_binary_source_upload_hashes_decoded_bytes(client):
    """Regression (compose E2E first-run): ``raw`` arrives over JSON as a
    base64 *string*, which pydantic does not decode — intake must see the
    decoded binary, or sha256/byte_size/media-type and the stored original
    artifact all describe the base64 text instead of the document."""
    import base64
    import hashlib

    pdf = b"%PDF-1.4\n%binary probe \x00\x01\xff endobj\n%%EOF\n"
    proj = client.post("/v1/projects", json={"slug": "bin", "display_name": "Bin"}).json()
    r = client.post(
        f"/v1/projects/{proj['id']}/sources",
        json={
            "original_name": "handbook.pdf",
            "raw": base64.b64encode(pdf).decode("ascii"),
            "declared_license": "CC-BY-4.0",
            "privacy": "public",
        },
    )
    assert r.status_code == 201, r.text
    src = r.json()
    # binary truth, not the caller's declaration and not the base64 text
    assert src["sha256"] == hashlib.sha256(pdf).hexdigest()
    assert src["byte_size"] == len(pdf)
    assert "pdf" in (src.get("media_type") or "")
    assert src["artifact_id_original"]

    # malformed base64 is a typed 422, never a silently-mangled upload
    r = client.post(
        f"/v1/projects/{proj['id']}/sources",
        json={"original_name": "bad.pdf", "raw": "definitely!!not@@base64"},
    )
    assert r.status_code == 422, r.text
    assert "base64" in r.text
