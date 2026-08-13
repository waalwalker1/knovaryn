"""Web console accessibility + surface tests (spec §17.4, WP J6).

The console at ``/`` is a single self-contained, keyboard-navigable page. These
tests assert the *real* surface (not a fake): every top-level feature required
by J6 — token setup, project creation, binary/text source intake with license +
privacy declaration, run estimate, profile/budget selection, pipeline queue +
live job event view, example review with cited evidence, quality report,
version creation, export download, publication dry-run — is reachable from the
console, and the page is dependency-free (no remote origins) so the CSP
``'self'`` stays effective.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from knovaryn.interfaces.rest.app import app
from knovaryn.interfaces.rest.webconsole import render_console


@pytest.fixture
def page() -> str:
    return render_console()


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Point the workspace at a throwaway sqlite file so tests don't touch the
    # repo's .knovaryn state or collide across runs.
    import knovaryn.application.workspace as ws_mod
    import knovaryn.interfaces.rest.app as rest_app

    db_url = f"sqlite+aiosqlite:///{tmp_path}/webconsole.db"

    def _fake_load_config():
        return {"storage.database_url": db_url}

    monkeypatch.setattr(ws_mod, "load_config", _fake_load_config)
    rest_app._workspace = None
    with TestClient(app) as c:
        yield c
    rest_app._workspace = None


pytestmark = [pytest.mark.rest]


def test_console_is_self_contained(page):
    """No external origin may leak a dependency into the page (keeps CSP 'self')."""
    assert "https://" not in page and "http://" not in page
    assert "cdn" not in page.lower()


def test_console_has_health_and_token(page):
    assert "/v1/health" in page
    assert "Bearer" in page and "token" in page


def test_console_project_surface(page):
    assert "/v1/projects" in page
    assert "slug" in page
    assert "display_name" in page


def test_console_source_surface(page):
    """Text + binary sources, license and privacy declaration (J6/G)."""
    assert "/sources" in page
    assert "declared_license" in page
    assert "privacy" in page
    assert 'type="file"' in page  # binary upload
    assert "arrayBuffer" in page  # client-side byte read


def test_console_pipeline_surface(page):
    """Estimate, profile/budget selection, queue, live job event view."""
    assert "/pipeline/estimate" in page
    assert "/pipeline" in page
    assert "profile" in page
    assert "budget_max_usd" in page
    assert "target_examples" in page
    assert "/run" in page and "/v1/jobs/" in page


def test_console_review_surface(page):
    """Example review with cited evidence and lineage."""
    assert "/examples" in page
    assert "/review" in page
    assert "approve" in page and "reject" in page and "needs_work" in page


def test_console_lifecycle_surface(page):
    """Quality report, version, export download, publication dry-run plan."""
    assert "/validate" in page
    assert "/version" in page
    assert "/export" in page
    assert "/publish" in page
    assert "dry_run" in page


def test_console_has_semantic_landmarks_and_labels(page):
    """Accessible HTML: landmarks, labelled controls, focus + aria-live."""
    assert "<main" in page
    assert "<header" in page
    assert "aria-labelledby" in page
    assert "aria-describedby" in page
    assert "aria-live" in page
    assert "focus-visible" in page


def test_console_over_http(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Knovaryn Console" in r.text
    assert "<script>" in r.text
