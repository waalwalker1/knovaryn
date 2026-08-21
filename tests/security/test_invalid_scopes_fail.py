"""Regression tests: invalid scopes fail (defect 4.10).

v0.1 silently FILTERED unknown scope names — and worse, a configuration whose
scopes were all invalid (one typo) resolved to "no known scopes", which the
old code answered by granting the FULL default set. A typo escalated to admin.
Corrected contract (fail closed):

* an unknown scope name is a configuration error raised at load time and at
  principal resolution — never silently filtered, never a fallback;
* an explicitly empty ``server.scopes`` list means NO privileges (every scoped
  operation answers 403); omitting the key means the safe default set.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

TOKEN = "typo-token-1"


@pytest.mark.rest
class TestInvalidScopesFail:
    """Invalid scope names must raise a startup/configuration error."""

    async def test_invalid_scope_name_fails(self, monkeypatch):
        from knovaryn.domain.config import load_config
        from knovaryn.domain.errors import ConfigurationError

        with pytest.raises(ConfigurationError, match="project:raed"):
            load_config(request_overrides={"server": {"scopes": ["project:raed"]}})

        # defense in depth: principal resolution refuses unknown scopes too —
        # even when load_config's own validation is bypassed with a hand-built
        # dict. The token must authenticate (bearer sees the same token) so the
        # scope resolution path itself is what refuses.
        import knovaryn.infrastructure.auth.bearer as bearer
        import knovaryn.interfaces.rest.security as sec

        server = {"api_token": TOKEN, "scopes": ["project:raed"]}
        monkeypatch.setattr(bearer, "load_config", lambda: {"server": server})
        monkeypatch.setattr(sec, "load_config", lambda: {"server": server})
        with pytest.raises(ConfigurationError):
            sec.resolve_principal(TOKEN)

    async def test_empty_scope_list_means_no_privileges(self, monkeypatch, tmp_path):
        import knovaryn.application.workspace as ws
        import knovaryn.infrastructure.auth.bearer as bearer
        import knovaryn.interfaces.rest.security as sec
        from knovaryn.interfaces.rest.app import app

        server = {"host": "127.0.0.1", "api_token": TOKEN, "scopes": []}
        monkeypatch.setattr(bearer, "load_config", lambda: {"server": server})
        monkeypatch.setattr(sec, "load_config", lambda: {"server": server})
        monkeypatch.setattr(
            ws,
            "load_config",
            lambda: {"storage.database_url": f"sqlite+aiosqlite:///{tmp_path}/ns.db"},
        )
        with TestClient(app) as client:
            h = {"Authorization": f"Bearer {TOKEN}"}
            r = client.get("/v1/projects", headers=h)
            assert r.status_code == 403, (
                f"explicit empty scope list must grant nothing, got {r.status_code}"
            )
            r2 = client.post("/v1/projects", json={"slug": "nope", "display_name": "No"}, headers=h)
            assert r2.status_code == 403
