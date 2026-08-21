"""Console auth + accessibility semantics (spec §17.4, WP J6).

The earlier placeholder skipped with "Web console not yet implemented" — but
the console EXISTS (``interfaces/rest/webconsole.py``) with real tests in
``tests/test_rest_webconsole.py``. This module covers the slice those don't:

* **auth**: with a server token configured, the console SHELL stays reachable
  (the page is where the operator pastes the token) while the API behind it
  refuses unauthenticated calls — and accepts them once the token is sent;
* **keyboard**: skip link + visible focus styles exist;
* **screen reader**: landmarks, labelled form controls, aria wiring;
* **responsive**: viewport meta and fluid layout (no fixed-width body).

All assertions run against the REAL rendered HTML and the REAL FastAPI app —
no browser binary needed, so these run in the ordinary offline suite.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from knovaryn.interfaces.rest.app import app
from knovaryn.interfaces.rest.webconsole import render_console

pytestmark = pytest.mark.rest


def _client_with_token(monkeypatch, tmp_path, token: str) -> TestClient:
    import knovaryn.application.workspace as ws_mod
    import knovaryn.infrastructure.auth.bearer as bearer
    import knovaryn.interfaces.rest.app as rest_app
    import knovaryn.interfaces.rest.security as sec

    db_url = f"sqlite+aiosqlite:///{tmp_path}/console-auth.db"

    def _fake_ws_config():
        return {"storage.database_url": db_url}

    server = {"host": "127.0.0.1", "api_token": token, "admin_principals": []}
    monkeypatch.setattr(ws_mod, "load_config", _fake_ws_config)
    monkeypatch.setattr(bearer, "load_config", lambda: {"server": server})
    monkeypatch.setattr(sec, "load_config", lambda: {"server": server})
    rest_app._workspace = None
    return TestClient(app)


class TestConsoleWithAuth:
    def test_console_shell_reachable_but_api_gated(self, monkeypatch, tmp_path):
        token = "console-test-token"
        with _client_with_token(monkeypatch, tmp_path, token) as c:
            # shell is the token-entry surface: served without credentials
            r = c.get("/")
            assert r.status_code == 200
            assert "Knovaryn Console" in r.text

            # the API behind it refuses unauthenticated calls...
            r = c.get("/v1/projects")
            assert r.status_code == 401
            # ...and accepts them once the console's Bearer header is sent
            r = c.get("/v1/projects", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200


class TestKeyboardNavigation:
    def test_skip_link_and_focus_styles(self):
        html = render_console()
        assert 'href="#main"' in html, "skip-to-content link missing"
        assert "focus-visible" in html, "no visible focus style for keyboard users"


class TestScreenReader:
    def test_landmarks_labels_and_aria(self):
        html = render_console()
        assert "<main" in html and "<header" in html, "page landmarks missing"
        assert "aria-live" in html or 'role="status"' in html, (
            "status region not announced to screen readers"
        )
        # every form control has a programmatic label
        import re

        for control in re.findall(r'<(?:input|select|textarea)[^>]*id="([^"]+)"', html):
            assert f'for="{control}"' in html, f"control #{control} has no <label for>"

    def test_no_remote_origins(self):
        """Self-contained page: CSP 'self' stays effective (no CDN calls)."""
        html = render_console()
        import re

        remote = re.findall(r'(?:src|href)="https?://[^"]+', html)
        assert not remote, f"console loads remote origins: {remote}"


class TestResponsive:
    def test_viewport_meta_and_fluid_layout(self):
        html = render_console()
        assert 'name="viewport" content="width=device-width, initial-scale=1"' in html
        # no fixed pixel body width that would break small screens
        import re

        assert not re.search(r"body\s*\{[^}]*width:\s*\d+px", html), "body has a fixed pixel width"
