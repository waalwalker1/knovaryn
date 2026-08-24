"""Unit tests for the MCP SDK dual-major compat adapter (``_compat.py``).

The coverage gate runs offline against an installed SDK 1.x, so the 2.x
import paths and the defensive branches would otherwise never execute.
These tests exercise them with stub modules/attributes injected at the same
seams the adapter resolves them (``sys.modules``, module attributes) —
no SDK 2.x wheel required:

* ``_context_class`` / ``_server_class`` under major 2 (the renamed classes);
* ``open_streamable_http`` under both majors, with and without the 2.x-bundled
  ``httpx2`` client;
* unavailable SDK → loud ImportError from ``build_mcp_server``;
* malformed / missing version metadata resolution.
"""

from __future__ import annotations

import asyncio
import importlib.machinery
import importlib.metadata
import sys
from contextlib import asynccontextmanager
from types import ModuleType

import pytest

import knovaryn.interfaces.mcp._compat as kc

pytestmark = [pytest.mark.unit]


class _FakeAsyncClient:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


def _install_fake_httpx(monkeypatch, name: str) -> ModuleType:
    # a plausible module: importlib.util.find_spec() — the adapter's httpx2
    # probe — rejects entries whose __spec__ is missing or None
    mod = ModuleType(name)
    mod.AsyncClient = _FakeAsyncClient
    mod.__spec__ = importlib.machinery.ModuleSpec(name, None)
    monkeypatch.setitem(sys.modules, name, mod)
    return mod


@asynccontextmanager
async def _fake_streamable_client(url, *, http_client=None):
    yield ("read-stream", "write-stream", lambda: "session-id")


@pytest.fixture
def fake_streamable_http(monkeypatch):
    """Patch the SDK's streamable-http client factory wherever it lives."""
    import mcp.client.streamable_http as mod  # imports if not yet loaded

    monkeypatch.setattr(mod, "streamable_http_client", _fake_streamable_client)


# -- version metadata ---------------------------------------------------------


def test_sdk_version_none_when_package_missing(monkeypatch):
    monkeypatch.setattr(kc, "mcp_available", lambda: False)
    assert kc.mcp_sdk_version() is None


def test_sdk_version_handles_missing_metadata(monkeypatch):
    monkeypatch.setattr(kc, "mcp_available", lambda: True)

    def raise_pnf(dist):
        raise importlib.metadata.PackageNotFoundError(dist)

    monkeypatch.setattr(importlib.metadata, "version", raise_pnf)
    assert kc.mcp_sdk_version() is None


def test_sdk_major_survives_malformed_metadata(monkeypatch):
    monkeypatch.setattr(kc, "mcp_sdk_version", lambda: "not-a-number")
    assert kc.mcp_sdk_major() is None


# -- class resolution per major -----------------------------------------------


def test_context_class_major2(monkeypatch):
    ctx_mod = ModuleType("mcp.server.mcpserver.context")
    sentinel = type("Context2", (), {})
    ctx_mod.Context = sentinel
    monkeypatch.setitem(sys.modules, "mcp.server.mcpserver.context", ctx_mod)
    monkeypatch.setattr(kc, "mcp_sdk_major", lambda: 2)
    assert kc._context_class() is sentinel


def test_server_class_major2(monkeypatch):
    server_pkg = sys.modules["mcp.server"]
    sentinel = type("MCPServer2", (), {})
    monkeypatch.setattr(server_pkg, "MCPServer", sentinel, raising=False)
    monkeypatch.setattr(kc, "mcp_sdk_major", lambda: 2)
    assert kc._server_class() is sentinel


def test_context_and_server_class_major1_real_sdk():
    """Under the installed 1.x SDK the real classes resolve (sanity anchor)."""
    if kc.mcp_sdk_major() != 1:
        pytest.skip("requires the real mcp 1.x install this env provides")
    from mcp.server.fastmcp import Context, FastMCP

    assert kc._context_class() is Context
    assert kc._server_class() is FastMCP


# -- build_mcp_server -----------------------------------------------------------


def test_build_mcp_server_without_sdk_raises_importerror(monkeypatch):
    monkeypatch.setattr(kc, "mcp_available", lambda: False)
    with pytest.raises(ImportError, match="knovaryn\\[mcp\\]"):
        kc.build_mcp_server("x", instructions="i", lifespan=None)


def test_build_mcp_server_settings_rebuild_importerror_is_swallowed(monkeypatch):
    """1.x point releases without the Settings module must not break startup."""

    class _NoSettings(ModuleType):
        pass

    shim = _NoSettings("mcp.server.fastmcp.server")  # no Settings attribute
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp.server", shim)

    calls: list[tuple[str, str]] = []

    class FakeServer:
        def __init__(self, name, *, instructions, lifespan):
            calls.append((name, instructions))

    monkeypatch.setattr(kc, "mcp_sdk_major", lambda: 1)
    fastmcp_pkg = sys.modules["mcp.server.fastmcp"]
    monkeypatch.setattr(fastmcp_pkg, "FastMCP", FakeServer)
    kc.build_mcp_server("svc", instructions="ins", lifespan=None)
    assert calls == [("svc", "ins")]


# -- open_streamable_http --------------------------------------------------------


def test_open_streamable_http_major2_with_httpx2(fake_streamable_http, monkeypatch):
    _install_fake_httpx(monkeypatch, "httpx2")
    monkeypatch.setattr(kc, "mcp_sdk_major", lambda: 2)

    async def scenario():
        async with kc.open_streamable_http("http://unit/test") as (read, write):
            return read, write

    read, write = asyncio.run(scenario())
    assert (read, write) == ("read-stream", "write-stream")


def test_open_streamable_http_major2_falls_back_to_httpx(fake_streamable_http, monkeypatch):
    """A 2.x install without its bundled httpx2 still connects via httpx."""
    import httpx as real_httpx  # noqa: F401 - proves the fallback import target exists

    monkeypatch.delitem(sys.modules, "httpx2", raising=False)
    monkeypatch.setattr(sys.modules["httpx"], "AsyncClient", _FakeAsyncClient, raising=False)
    monkeypatch.setattr(kc, "mcp_sdk_major", lambda: 2)

    async def scenario():
        async with kc.open_streamable_http("http://unit/test") as (read, write):
            return read, write

    read, write = asyncio.run(scenario())
    assert (read, write) == ("read-stream", "write-stream")


def test_open_streamable_http_major1_uses_httpx(fake_streamable_http, monkeypatch):
    monkeypatch.setattr(kc, "mcp_sdk_major", lambda: 1)
    monkeypatch.setattr(sys.modules["httpx"], "AsyncClient", _FakeAsyncClient, raising=False)

    async def scenario():
        async with kc.open_streamable_http(
            "http://unit/test", headers={"Authorization": "Bearer t"}
        ) as (read, write):
            return read, write

    read, write = asyncio.run(scenario())
    assert (read, write) == ("read-stream", "write-stream")


def test_supported_majors_match_contract():
    """The declared dependency range stays in lockstep with the matrix."""
    assert kc.SUPPORTED_MCP_MAJORS == (1, 2)
    assert kc.MIN_SUPPORTED_MCP_VERSION == "1.28"
