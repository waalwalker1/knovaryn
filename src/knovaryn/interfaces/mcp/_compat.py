"""Narrow MCP SDK compatibility adapter (defect 3.1, v0.2.1).

The declared dependency range is ``mcp>=1.28,<3`` — two SDK majors with one
breaking rename between them:

* **1.x** — high-level server is ``mcp.server.fastmcp.FastMCP``; the injected
  tool/resource ``Context`` lives in the same module.
* **2.x** — the server is ``MCPServer`` (import from ``mcp.server``); the
  high-level ``Context`` moved to ``mcp.server.mcpserver.context``.

Everything else Knovaryn uses is API-identical across both majors and is
proven so by the acceptance matrix (``scripts/mcp_acceptance_matrix.py`` +
``tests/release/test_mcp_acceptance_matrix.py``): the ``@server.tool()`` /
``@server.resource()`` decorators with signature-inspected ``Context``
injection, the lifespan protocol yielding the workspace,
``ctx.request_context.lifespan_context``, ``run(transport="stdio")`` and
``streamable_http_app()``.

This module is the ONLY place that knows the split. ``server.py``, the entry
point, and the tests import the unified names from here; no application logic
may branch on the SDK version.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
from contextlib import AbstractAsyncContextManager
from typing import Any, cast

# Majors the Knovaryn MCP adapter is tested against end-to-end (clean venv per
# major, full stdio + streamable-HTTP lifecycle). The declared dependency
# range in pyproject.toml must stay in lockstep with this tuple.
SUPPORTED_MCP_MAJORS: tuple[int, ...] = (1, 2)

# Floor of the 1.x line we claim: the contract's Strategy-A floor. Older 1.x
# releases are not exercised by the matrix and therefore not claimed.
MIN_SUPPORTED_MCP_VERSION = "1.28"

SERVER_CLS_NAME_1X = "FastMCP"
SERVER_CLS_NAME_2X = "MCPServer"


def mcp_available() -> bool:
    """True when the ``mcp`` package is importable."""
    return importlib.util.find_spec("mcp") is not None


def mcp_sdk_version() -> str | None:
    """Installed ``mcp`` distribution version, or None when absent."""
    if not mcp_available():
        return None
    try:
        return importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover
        return None


def mcp_sdk_major() -> int | None:
    """Installed SDK major version, or None when ``mcp`` is absent."""
    version = mcp_sdk_version()
    if version is None:
        return None
    try:
        return int(version.split(".")[0])
    except (ValueError, IndexError):  # pragma: no cover - malformed metadata
        return None


def _context_class() -> type[Any]:
    """The high-level ``Context`` class for the installed SDK major.

    Used for tool/resource signature annotations: both majors inspect tool
    signatures and inject the context object into the parameter annotated
    with this class.
    """
    major = mcp_sdk_major()
    if major == 2:
        from mcp.server.mcpserver.context import Context as Context2

        return cast("type[Any]", Context2)
    from mcp.server.fastmcp import Context as Context1

    return cast("type[Any]", Context1)


def _server_class() -> type[Any]:
    """The high-level server class for the installed SDK major."""
    major = mcp_sdk_major()
    if major == 2:
        from mcp.server import MCPServer as Server2  # type: ignore[attr-defined]

        return cast("type[Any]", Server2)
    from mcp.server.fastmcp import FastMCP as Server1

    return cast("type[Any]", Server1)


def _rebuild_sdk_settings() -> None:
    """Resolve the 1.x SDK Settings model's forward refs (defect 3.2).

    1.x's ``mcp.server.fastmcp.server.Settings`` annotates ``lifespan`` with a
    forward reference to ``FastMCP`` that pydantic never resolves, so every
    server construction emits pydantic_settings'
    ``IncompleteFieldDefinitionWarning``. Rebuilding the model once — now that
    the module is fully imported — fixes the warning at its source instead of
    filtering it (contract §9 warnings-as-errors). 2.x's equivalent Settings is
    a plain BaseModel and does not warn.
    """
    if mcp_sdk_major() != 1:
        return
    try:
        from mcp.server.fastmcp.server import Settings as Settings1

        Settings1.model_rebuild()
    except ImportError:  # pragma: no cover - defensive across 1.x point releases
        pass


def build_mcp_server(
    name: str,
    *,
    instructions: str,
    lifespan: Any,
) -> Any:
    """Construct the high-level MCP server, hiding the major-version rename.

    Both constructors accept the positional ``name`` plus the ``instructions``
    and ``lifespan`` keywords with identical semantics (lifespan is an
    async-context-manager factory whose yield value becomes
    ``ctx.request_context.lifespan_context``).
    """
    if not mcp_available():
        raise ImportError(
            "The MCP server requires the 'mcp' package. Install it (e.g. "
            "pip install 'knovaryn[mcp]') or run Knovaryn via the CLI/REST instead."
        )
    _rebuild_sdk_settings()
    server_cls = _server_class()
    return server_cls(name, instructions=instructions, lifespan=lifespan)


def open_streamable_http(
    url: str, headers: dict[str, str] | None = None
) -> AbstractAsyncContextManager[tuple[Any, Any]]:
    """Client-side Streamable HTTP connection, identical across SDK majors.

    Both majors expose snake_case ``streamable_http_client(url, *,
    http_client=...)``; custom headers go through the provided HTTP client.
    1.x bundles that client as ``httpx``, 2.x renamed it ``httpx2``. The
    yielded arity differs (1.x appends ``get_session_id``), so exactly the
    ``(read, write)`` pair is yielded here.
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _ctx() -> Any:
        from mcp.client.streamable_http import streamable_http_client

        if mcp_sdk_major() == 2:
            import importlib.util

            if importlib.util.find_spec("httpx2") is not None:
                import httpx2 as httpx_mod  # type: ignore[import-not-found]
            else:
                import httpx as httpx_mod
        else:
            import httpx as httpx_mod

        async with (
            httpx_mod.AsyncClient(headers=headers or {}, timeout=30.0) as hc,
            streamable_http_client(url, http_client=hc) as streams,
        ):
            yield streams[0], streams[1]

    return _ctx()


__all__ = [
    "MIN_SUPPORTED_MCP_VERSION",
    "SERVER_CLS_NAME_1X",
    "SERVER_CLS_NAME_2X",
    "SUPPORTED_MCP_MAJORS",
    "build_mcp_server",
    "mcp_available",
    "mcp_sdk_major",
    "mcp_sdk_version",
    "open_streamable_http",
]
