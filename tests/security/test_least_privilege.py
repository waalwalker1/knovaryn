"""Regression tests: least-privilege scopes (defect 4.10).

v0.1 granted every configured token the FULL scope set — including ``admin``
(cross-tenant bypass) and ``datasets:publish`` — while its own docstring
claimed those "remain explicit". A leaked remote token was therefore a
full-admin credential. Corrected contract:

* a configured token, with ``server.scopes`` omitted, gets the default remote
  surface WITHOUT ``admin`` and WITHOUT ``datasets:publish``;
* ``/v1/metrics`` (admin scope) and the publish endpoint answer 403;
* the loopback operator principal (``local``) keeps the full surface.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

TOKEN = "least-priv-token-1"


def _patch_auth(monkeypatch, *, token: str, scopes: list[str] | None) -> None:
    """Patch the auth/security config consumers (``scopes=None`` = omitted)."""
    import knovaryn.infrastructure.auth.bearer as bearer
    import knovaryn.interfaces.rest.security as sec

    server: dict = {"host": "127.0.0.1", "api_token": token, "admin_principals": []}
    if scopes is None:
        server["scopes"] = None  # omitted from config
    else:
        server["scopes"] = scopes
    monkeypatch.setattr(bearer, "load_config", lambda: {"server": server})
    monkeypatch.setattr(sec, "load_config", lambda: {"server": server})


@pytest.fixture
def client(monkeypatch, tmp_path):
    import knovaryn.application.workspace as ws
    from knovaryn.interfaces.rest.app import app

    db_url = f"sqlite+aiosqlite:///{tmp_path}/lp.db"
    monkeypatch.setattr(ws, "load_config", lambda: {"storage.database_url": db_url})
    with TestClient(app) as c:
        yield c


@pytest.mark.rest
class TestLeastPrivilege:
    """Remote tokens must not receive admin/publish by default."""

    async def test_admin_denied_by_default(self, monkeypatch, client):
        _patch_auth(monkeypatch, token=TOKEN, scopes=None)  # scopes omitted
        h = {"Authorization": f"Bearer {TOKEN}"}
        r = client.get("/v1/metrics", headers=h)
        assert r.status_code == 403, (
            f"admin scope must not be granted by default, got {r.status_code}"
        )

        # unit-level: the resolved principal carries neither admin nor publish
        import knovaryn.interfaces.rest.security as sec

        p = sec.resolve_principal(TOKEN)
        assert "admin" not in p.scopes
        assert "datasets:publish" not in p.scopes
        # ordinary surface still works with the default remote set
        r2 = client.get("/v1/projects", headers=h)
        assert r2.status_code == 200

    async def test_publish_denied_by_default(self, monkeypatch, client):
        _patch_auth(monkeypatch, token=TOKEN, scopes=None)
        h = {"Authorization": f"Bearer {TOKEN}"}
        proj = client.post(
            "/v1/projects", json={"slug": "lp", "display_name": "LP"}, headers=h
        ).json()
        r = client.post(
            f"/v1/projects/{proj['id']}/publish",
            json={"repo_id": "local/lp", "dry_run": True, "confirm": True},
            headers=h,
        )
        assert r.status_code == 403, (
            f"datasets:publish must not be granted by default, got {r.status_code}"
        )

        # explicit opt-in grants it (least privilege is a dial, not a wall)
        _patch_auth(
            monkeypatch,
            token=TOKEN,
            scopes=["projects:read", "projects:write", "datasets:publish"],
        )
        r2 = client.post(
            f"/v1/projects/{proj['id']}/publish",
            json={"repo_id": "local/lp", "dry_run": True, "confirm": True},
            headers=h,
        )
        assert r2.status_code != 403, "explicitly granted publish scope must pass the gate"

    async def test_local_principal_keeps_full_surface(self, monkeypatch):
        import knovaryn.interfaces.rest.security as sec

        p = sec.resolve_principal(None)  # no token configured → loopback operator
        assert "admin" in p.scopes
        assert "datasets:publish" in p.scopes
