"""Regression tests: remote MCP authentication.

v0.1's streamable-http transport hosted the FastMCP ASGI app with uvicorn and
NO authentication: anyone who could reach the port had the operator's full
workspace. Corrected contract (mirrors REST J2/J3):

* when ``server.api_token`` is configured, the MCP HTTP app rejects requests
  with a missing or wrong bearer token (401, fail closed);
* a correct bearer token passes through to the MCP app;
* with no token configured the app stays loopback-local (bind safety is the
  non-loopback refusal's job, tested in test_nonloopback_refusal.py).
"""

from __future__ import annotations

from typing import Any

import pytest


async def _call_asgi(app: Any, headers: dict[str, str], method: str = "POST") -> int:
    """Drive a raw ASGI call and return the response status."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": method,
        "path": "/mcp",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg: dict) -> None:
        sent.append(msg)

    await app(scope, receive, send)
    assert sent, "ASGI app produced no response start"
    return int(sent[0]["status"])


def _patch_token(monkeypatch, token: str) -> None:
    import knovaryn.interfaces.mcp.server as mcp_server

    monkeypatch.setattr(
        mcp_server,
        "load_config",
        lambda: {"server": {"host": "127.0.0.1", "api_token": token}},
    )


@pytest.mark.mcp
class TestRemoteAuth:
    """Streamable HTTP MCP must be authenticated."""

    async def test_missing_token_rejected(self, monkeypatch):
        from knovaryn.interfaces.mcp.server import build_authenticated_http_app, build_server

        _patch_token(monkeypatch, "s3cret-token")
        server = build_server(database_url="sqlite+aiosqlite:///:memory:")
        app = build_authenticated_http_app(server)
        assert await _call_asgi(app, headers={}) == 401
        # non-bearer schemes are rejected too
        assert await _call_asgi(app, headers={"Authorization": "Basic dXNlcjpwdw=="}) == 401

    async def test_wrong_token_rejected(self, monkeypatch):
        from knovaryn.interfaces.mcp.server import build_authenticated_http_app, build_server

        _patch_token(monkeypatch, "s3cret-token")
        server = build_server(database_url="sqlite+aiosqlite:///:memory:")
        app = build_authenticated_http_app(server)
        assert await _call_asgi(app, headers={"Authorization": "Bearer wrong"}) == 401

    async def test_correct_token_reaches_mcp_app(self, monkeypatch):
        """A valid bearer token must pass the guard and reach the inner app."""
        from knovaryn.interfaces.mcp.server import bearer_guard

        reached: list[dict] = []

        async def inner(scope, receive, send) -> None:  # noqa: ANN001
            reached.append(scope)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        guarded = bearer_guard(inner, token="s3cret-token")
        assert await _call_asgi(guarded, {"Authorization": "Bearer s3cret-token"}) == 200
        assert reached, "valid token must reach the wrapped app"

    async def test_no_token_configured_stays_loopback_local(self, monkeypatch):
        """Without a configured token the HTTP app is not token-gated (the
        non-loopback bind refusal is what protects this mode)."""
        from knovaryn.interfaces.mcp.server import bearer_guard

        async def inner(scope, receive, send) -> None:  # noqa: ANN001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        guarded = bearer_guard(inner, token="")
        assert await _call_asgi(guarded, headers={}) == 200
