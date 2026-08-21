"""REST authorization + safe-binding tests (spec §23, WP J3/J4).

Exercises scope gating (missing scope -> 403), owner-tenant isolation (a
non-admin principal cannot read another's project -> 403), admin bypass, and
safe binding (refusing a non-loopback bind without an API token). Runs offline.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

TOKEN = "test-secret-token-123"


def _patch_auth(
    monkeypatch,
    *,
    token: str,
    scopes: list[str],
    admin: list[str] | None = None,
    host: str = "0.0.0.0",
    allow_insecure: bool = False,
) -> None:
    """Patch ONLY the auth/security load_config consumers (not the workspace's,
    which the client fixture controls so the DB stays on a tmp file)."""
    import knovaryn.infrastructure.auth.bearer as bearer
    import knovaryn.interfaces.rest.security as sec

    server = {
        "host": host,
        "api_token": token,
        "scopes": scopes,
        "admin_principals": admin or [],
        "allow_insecure_nonloopback": allow_insecure,
    }

    monkeypatch.setattr(bearer, "load_config", lambda: {"server": server})
    monkeypatch.setattr(sec, "load_config", lambda: {"server": server})
    return server


@pytest.fixture
def client(monkeypatch, tmp_path):
    import knovaryn.application.workspace as ws
    from knovaryn.interfaces.rest.app import app

    db_url = f"sqlite+aiosqlite:///{tmp_path}/sec.db"
    monkeypatch.setattr(ws, "load_config", lambda: {"storage.database_url": db_url})
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------- scopes / 401
pytestmark = [pytest.mark.rest]


def test_missing_token_returns_401(monkeypatch, client):
    _patch_auth(monkeypatch, token=TOKEN, scopes=[])
    r = client.get("/v1/projects")
    assert r.status_code == 401


def test_wrong_token_returns_401(monkeypatch, client):
    _patch_auth(monkeypatch, token=TOKEN, scopes=[])
    r = client.get("/v1/projects", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_full_scope_can_create_and_list(monkeypatch, client):
    # defect 4.10: an explicitly configured FULL canonical scope list grants
    # everything (an empty list now means NO privileges — never "full").
    import knovaryn.interfaces.rest.security as sec

    _patch_auth(monkeypatch, token=TOKEN, scopes=sorted(sec.DEFAULT_GRANTED_SCOPES))
    h = {"Authorization": f"Bearer {TOKEN}"}
    r = client.post("/v1/projects", json={"slug": "adm", "display_name": "Adm"}, headers=h)
    assert r.status_code == 201, r.text
    r = client.get("/v1/projects", headers=h)
    assert r.status_code == 200
    assert r.json()["projects"]


def test_limited_scope_writes_denied(monkeypatch, client):
    # read-only token cannot create a project (projects:write denied) -> 403,
    # but can list -> 200. Never a silent pass on a denied scope (rule 6).
    _patch_auth(monkeypatch, token=TOKEN, scopes=["projects:read"])
    h = {"Authorization": f"Bearer {TOKEN}"}
    r = client.post("/v1/projects", json={"slug": "lim", "display_name": "Lim"}, headers=h)
    assert r.status_code == 403
    r = client.get("/v1/projects", headers=h)
    assert r.status_code == 200


def test_publish_requires_publish_scope(monkeypatch, client):
    _patch_auth(monkeypatch, token=TOKEN, scopes=["projects:read", "projects:write"])
    h = {"Authorization": f"Bearer {TOKEN}"}
    proj = client.post("/v1/projects", json={"slug": "pp", "display_name": "PP"}, headers=h).json()
    r = client.post(
        f"/v1/projects/{proj['id']}/publish",
        json={"repo_id": "local/pp", "dry_run": True, "confirm": True},
        headers=h,
    )
    assert r.status_code == 403


# --------------------------------------------------------- owner tenancy
def test_owner_tenant_isolation(monkeypatch, client):
    """Two tokens = two distinct principals; alice cannot see/read bob's
    project (owner-tenant isolation enforced at the app-service layer)."""
    import knovaryn.interfaces.rest.security as sec

    _patch_auth(monkeypatch, token="", scopes=[])
    # Principal names come from the token identity resolver.
    identity = {"alice-t": "alice", "bob-t": "bob"}
    orig = sec.resolve_principal

    def fake_resolve(token):
        pr = orig(token)
        if token in identity:
            pr.name = identity[token]
        return pr

    monkeypatch.setattr(sec, "resolve_principal", fake_resolve)
    monkeypatch.setattr(sec, "_configured_scopes", lambda n: set(sec.DEFAULT_GRANTED_SCOPES))

    alice = {"Authorization": "Bearer alice-t"}
    bob = {"Authorization": "Bearer bob-t"}
    client.post("/v1/projects", json={"slug": "a1", "display_name": "A1"}, headers=alice).json()
    client.post("/v1/projects", json={"slug": "b1", "display_name": "B1"}, headers=bob)

    # alice sees only her project
    visible = client.get("/v1/projects", headers=alice).json()["projects"]
    slugs = {p["slug"] for p in visible}
    assert "a1" in slugs and "b1" not in slugs

    # alice cannot GET bob's project (403)
    bob_id = client.get("/v1/projects", headers=bob).json()["projects"][0]["id"]
    r = client.get(f"/v1/projects/{bob_id}", headers=alice)
    assert r.status_code == 403


def test_admin_bypasses_tenancy(monkeypatch, client):
    import knovaryn.interfaces.rest.security as sec

    _patch_auth(monkeypatch, token="", scopes=[], admin=["alice", "bob2s"])
    orig = sec.resolve_principal

    def fake_resolve(token):
        pr = orig(token)
        if token in ("alice-t", "bob-t"):
            pr.name = {"alice-t": "alice", "bob-t": "bob"}[token]
        return pr

    monkeypatch.setattr(sec, "resolve_principal", fake_resolve)
    monkeypatch.setattr(sec, "_configured_scopes", lambda n: set(sec.DEFAULT_GRANTED_SCOPES))
    # admin_principals reaches the workspace service layer
    import knovaryn.application.workspace as ws

    server = {"server": {"api_token": "", "admin_principals": ["alice"]}}
    monkeypatch.setattr(ws, "load_config", lambda: server)

    admin = {"Authorization": "Bearer alice-t"}
    bob = {"Authorization": "Bearer bob-t"}
    client.post("/v1/projects", json={"slug": "ab", "display_name": "AB"}, headers=admin)
    client.post("/v1/projects", json={"slug": "bb", "display_name": "BB"}, headers=bob)
    bob_id = client.get("/v1/projects", headers=bob).json()["projects"][0]["id"]
    # admin principal can read bob's project
    r = client.get(f"/v1/projects/{bob_id}", headers=admin)
    assert r.status_code == 200


# ---------------------------------------------------------------- J4 binding
def test_safe_binding_refuses_nonloopback_without_token(monkeypatch):
    from knovaryn.domain.errors import ConfigurationError
    from knovaryn.interfaces.rest.security import server_bind_checked

    _patch_auth(monkeypatch, token="", scopes=[], host="0.0.0.0", allow_insecure=False)
    with pytest.raises(ConfigurationError):
        server_bind_checked()


def test_safe_binding_allows_loopback_without_token(monkeypatch):
    from knovaryn.interfaces.rest.security import server_bind_checked

    _patch_auth(monkeypatch, token="", scopes=[], host="127.0.0.1", allow_insecure=False)
    host, _port = server_bind_checked()
    assert host == "127.0.0.1"


def test_safe_binding_allows_nonloopback_with_token(monkeypatch):
    from knovaryn.interfaces.rest.security import server_bind_checked

    _patch_auth(monkeypatch, token=TOKEN, scopes=[], host="0.0.0.0", allow_insecure=False)
    host, _port = server_bind_checked()
    assert host == "0.0.0.0"


def test_safe_binding_allows_nonloopback_with_override(monkeypatch):
    from knovaryn.interfaces.rest.security import server_bind_checked

    _patch_auth(monkeypatch, token="", scopes=[], host="0.0.0.0", allow_insecure=True)
    host, _port = server_bind_checked()
    assert host == "0.0.0.0"
