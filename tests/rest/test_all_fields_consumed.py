"""Regression tests: REST API consumes all fields.

v0.1 accepted request fields and silently dropped them: ``SourceAdd.privacy``
never reached the persisted source, and ``PipelineStart.profile`` /
``budget_max_usd`` / ``target_examples`` were ignored (the profile one also
fed defect 4.9 — a requested live profile silently ran fake). Rule: a declared
request field is either consumed into durable state or rejected — never
swallowed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def env(monkeypatch, tmp_path):
    import knovaryn.application.workspace as ws
    import knovaryn.infrastructure.auth.bearer as bearer
    import knovaryn.interfaces.rest.security as sec
    from knovaryn.interfaces.rest.app import app

    db_url = f"sqlite+aiosqlite:///{tmp_path}/af.db"
    server = {"host": "127.0.0.1", "api_token": "", "scopes": None}
    monkeypatch.setattr(bearer, "load_config", lambda: {"server": server})
    monkeypatch.setattr(sec, "load_config", lambda: {"server": server})
    monkeypatch.setattr(ws, "load_config", lambda: {"storage.database_url": db_url})
    with TestClient(app) as c:
        yield SimpleNamespace(client=c, db_url=db_url)


@pytest.mark.rest
class TestAllFieldsConsumed:
    """Every REST request field must be consumed into durable state."""

    async def test_all_fields_persisted(self, env):
        c = env.client
        # -- project: every ProjectCreate field round-trips
        r = c.post(
            "/v1/projects",
            json={
                "slug": "fields",
                "display_name": "Fields Project",
                "description": "every field matters",
                "tags": ["alpha", "beta"],
            },
        )
        assert r.status_code == 201, r.text
        proj = r.json()
        assert proj["description"] == "every field matters"
        assert proj["tags"] == ["alpha", "beta"]

        # -- source: declared_license AND privacy must persist
        r = c.post(
            f"/v1/projects/{proj['id']}/sources",
            json={
                "original_name": "notes.md",
                "content": "# Notes\nSome content for the foundry.",
                "declared_license": "CC-BY-4.0",
                "privacy": "internal",
            },
        )
        assert r.status_code in (200, 201), r.text
        src = r.json()
        assert src["declared_license"] == "CC-BY-4.0"
        assert src["privacy_classification"] == "internal", (
            f"SourceAdd.privacy was silently dropped: {src.get('privacy_classification')!r}"
        )

        # -- pipeline start: profile / budget_max_usd / target_examples must
        # reach the durable job input (the stage consumes them from there)
        r = c.post(
            f"/v1/projects/{proj['id']}/pipeline",
            json={
                "task_family_proportions": {"factual_explanation": 1.0},
                "profile": "offline-demo",
                "budget_max_usd": 12.5,
                "target_examples": 42,
            },
        )
        assert r.status_code == 202, r.text
        job_id = r.json()["id"]

        from knovaryn.application.workspace import Workspace

        ws = Workspace(database_url=env.db_url)
        summary = await ws.get_job(job_id)
        pcfg = summary.job.input.get("pipeline", {})
        assert pcfg.get("profile") == "offline-demo"
        assert pcfg.get("budget_max_usd") == 12.5
        assert pcfg.get("target_examples") == 42
