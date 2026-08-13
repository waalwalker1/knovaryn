"""``knovaryn-mcp`` entry point (spec §17 / WP F1, F3).

Runs the Knovaryn MCP server over a chosen transport. The CLI entry point is
declared in ``pyproject.toml`` under ``[project.scripts]`` and the ``knovaryn
mcp`` subcommand delegates here.

Transports (WP F3):
* ``stdio`` (default) — the canonical MCP host transport.
* ``streamable-http`` — for remote/SSE-free HTTP hosting.

For streamable-http the server is exposed as a Starlette app
(``streamable_http_app``) and hosted with uvicorn on the requested host/port;
this is what makes ``--transport streamable-http`` a real network service.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="knovaryn-mcp",
        description="Knovaryn MCP server (offline training-data foundry).",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport to serve on (default: stdio).",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Bind host for streamable-http (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port for streamable-http (default: 8000).",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="SQLAlchemy database URL (default: config storage.database_url).",
    )
    args = parser.parse_args(argv)

    from .server import build_server

    server = build_server(database_url=args.database_url)

    if args.transport == "streamable-http":
        # FastMCP ships the server as a Starlette app; host it with uvicorn so
        # the host/port flags are honored (FastMCP.run() accepts no host/port).
        import uvicorn

        host = args.host or "127.0.0.1"
        port = args.port or 8000
        uvicorn.run(server.streamable_http_app(), host=host, port=port, log_level="info")
        return 0

    # stdio is the default and simplest: no host/port needed.
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["main"]
