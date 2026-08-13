"""Web-security middleware tests (spec §17.4, WP J5).

Verifies secure headers (CSP, X-Content-Type-Options, X-Frame-Options,
Referrer-Policy, Permissions-Policy), body-size limiting (413), and error
redaction (no traceback/secret leakage in failure responses). Runs offline.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import knovaryn.interfaces.rest.security_middleware as sm


@pytest.fixture
def client(monkeypatch, tmp_path):
    import knovaryn.application.workspace as ws
    from knovaryn.interfaces.rest.app import app

    monkeypatch.setattr(
        ws, "load_config", lambda: {"storage.database_url": f"sqlite+aiosqlite:///{tmp_path}/ws.db"}
    )
    with TestClient(app) as c:
        yield c


pytestmark = [pytest.mark.rest]


def test_security_headers_present(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    h = r.headers
    assert h.get("x-content-type-options") == "nosniff"
    assert h.get("x-frame-options") == "DENY"
    assert "default-src 'self'" in h.get("content-security-policy", "")
    assert h.get("referrer-policy") == "same-origin"
    assert "geolocation=()" in h.get("permissions-policy", "")


def test_cors_denied_when_no_allowlist(client):
    # No configured CORS origin -> preflight is denied (no allow-origin header).
    r = client.options(
        "/v1/projects",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in r.headers


def test_oversized_body_rejected_413(monkeypatch, client):
    # Cap the upload at a tiny size so a modest body trips the limit (413).
    monkeypatch.setattr(
        sm,
        "load_config",
        lambda: {"server": {"rate_limit": {"max_upload_bytes": 100}}},
    )
    big = json.dumps(
        {"slug": "x", "display_name": "Y" * 500}  # far over 100 bytes
    )
    r = client.post(
        "/v1/projects",
        content=big.encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 413


def test_error_response_is_redacted(client):
    """A 404/validation error returns a redacted detail, never a traceback."""
    r = client.get("/v1/projects/nope")
    assert r.status_code == 404
    body = r.json()
    assert "detail" in body
    # no python traceback / source path leaked
    assert "Traceback" not in r.text
    assert "workspace.py" not in r.text
