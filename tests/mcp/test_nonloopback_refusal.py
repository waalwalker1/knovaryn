"""Regression tests: non-loopback MCP refusal.

v0.1's ``knovaryn-mcp --transport streamable-http --host 0.0.0.0`` happily
exposed an unauthenticated MCP server on every interface. Corrected contract
(mirrors REST J4): the entry point refuses a non-loopback bind when no API
token is configured, unless the operator explicitly sets
``server.allow_insecure_nonloopback``.
"""

from __future__ import annotations

import pytest


@pytest.mark.mcp
class TestNonloopbackRefusal:
    """Non-loopback MCP bind must require authentication."""

    async def test_remote_bind_refused_without_auth(self, monkeypatch):
        import knovaryn.interfaces.mcp.server as mcp_server
        from knovaryn.domain.errors import ConfigurationError

        monkeypatch.setattr(
            mcp_server,
            "load_config",
            lambda: {"server": {"host": "0.0.0.0", "api_token": ""}},
        )
        with pytest.raises(ConfigurationError, match="non-loopback"):
            mcp_server.mcp_bind_checked("0.0.0.0", 8000)

    async def test_remote_bind_allowed_with_token(self, monkeypatch):
        import knovaryn.interfaces.mcp.server as mcp_server

        monkeypatch.setattr(
            mcp_server,
            "load_config",
            lambda: {"server": {"host": "0.0.0.0", "api_token": "s3cret"}},
        )
        host, port = mcp_server.mcp_bind_checked("0.0.0.0", 8123)
        assert (host, port) == ("0.0.0.0", 8123)

    async def test_main_refuses_remote_bind_without_token(self, monkeypatch):
        """The CLI entry point must enforce the same policy before serving."""
        import knovaryn.interfaces.mcp.__main__ as mcp_main
        import knovaryn.interfaces.mcp.server as mcp_server
        from knovaryn.domain.errors import ConfigurationError

        monkeypatch.setattr(
            mcp_server,
            "load_config",
            lambda: {"server": {"host": "0.0.0.0", "api_token": ""}},
        )
        with pytest.raises(ConfigurationError):
            mcp_main.main(
                [
                    "--transport",
                    "streamable-http",
                    "--host",
                    "0.0.0.0",
                    "--database-url",
                    "sqlite+aiosqlite:///:memory:",
                ]
            )

    async def test_explicit_override_allows_insecure_bind(self, monkeypatch):
        import knovaryn.interfaces.mcp.server as mcp_server

        monkeypatch.setattr(
            mcp_server,
            "load_config",
            lambda: {
                "server": {
                    "host": "0.0.0.0",
                    "api_token": "",
                    "allow_insecure_nonloopback": True,
                }
            },
        )
        host, _port = mcp_server.mcp_bind_checked("0.0.0.0", 8000)
        assert host == "0.0.0.0"
