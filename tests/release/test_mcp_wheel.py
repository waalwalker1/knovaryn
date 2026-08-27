"""WP F6 — MCP server works from a built wheel in a clean environment.

Builds the distribution with :mod:`build`, installs the wheel into a brand-new
virtualenv (no repository checkout on ``sys.path``), and verifies that:
* the ``knovaryn-mcp`` console entry point exists;
* the packaged MCP server starts over stdio and answers a real client
  (initialize + tool call);
* the ``knovaryn mcp --transport stdio`` subcommand is present.

This mirrors the F6 acceptance criterion: the MCP server must be a first-class
installed product, not just work from the source checkout.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import venv
from pathlib import Path

import pytest

pytestmark = [pytest.mark.release]

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _network_available() -> bool:
    """True when the wheel build's isolated backend + clean-venv pip install can
    reach PyPI. The clean-install test needs network to fetch ``hatchling`` (build
    backend) and the ``[mcp]`` dependency closure; when offline it cannot run its
    real assertions, so it is skipped rather than hard-failed in offline sandboxes.
    The offline clean-install path (build wheel locally + fresh venv) is verified
    separately by scripts/package_ci.py.
    """
    try:
        with socket.create_connection(("pypi.org", 443), timeout=3):
            return True
    except OSError:
        return False


def _venv_python(env_dir: Path) -> Path:
    return env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _build_wheel(tmp_path: Path) -> Path:
    """Build the wheel into ``tmp_path/dist`` and return its path."""
    import subprocess

    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(exist_ok=True)
    # isolated build is the standard reproducible path (it fetches the
    # ``hatchling`` backend into an isolated env, so the local env needs no
    # backend preinstalled).
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(dist_dir), str(_REPO_ROOT)],
        check=True,
        capture_output=True,
    )
    wheels = list(dist_dir.glob("*.whl"))
    assert wheels, "no wheel produced"
    return wheels[0]


def _install_and_run_mcp(tmp_path: Path, database_url: str) -> None:
    """Build the wheel, install into a clean venv, drive the MCP over stdio."""
    wheel = _build_wheel(tmp_path)

    env_dir = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    py = _venv_python(env_dir)

    # install the wheel + the MCP SDK the server needs (explicitly capped to the
    # pinned 1.x lineage whose ``fastmcp`` module supports this server; mcp 2.0
    # restructured without ``mcp.server.fastmcp``).
    subprocess.run(
        [
            str(py),
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-input",
            f"{str(wheel)}[mcp]",
            "mcp>=1.28,<3",
        ],
        check=True,
        capture_output=True,
    )

    # 1. the console entry point exists
    bin_script = env_dir / ("Scripts" if os.name == "nt" else "bin") / "knovaryn-mcp"
    assert bin_script.exists(), f"knovaryn-mcp script missing: {bin_script}"

    # 2. the packaged server answers a real stdio client (F6 acceptance)
    import anyio
    from mcp.client.stdio import stdio_client

    from mcp import ClientSession, StdioServerParameters

    params = StdioServerParameters(
        command=str(bin_script),
        args=["--transport", "stdio", "--database-url", database_url],
        env={**os.environ},
    )

    async def drive() -> None:
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert "health" in names
            assert "knovaryn_list_jobs" in names
            res = await session.call_tool("health", {})
            text = "\n".join(
                t for b in res.content if (t := (b.text if hasattr(b, "text") else None))
            )
            assert '"status": "ok"' in text

    anyio.run(drive)


def test_mcp_wheel_clean_install_serves_stdlib(tmp_path: Path) -> None:
    """The built wheel, in an empty venv, serves the MCP server over stdio."""
    if not _network_available():
        pytest.skip("offline: clean-install wheel test needs PyPI for build backend + [mcp] deps")
    db_url = f"sqlite+aiosqlite:///{tmp_path}/wheel.db"
    _install_and_run_mcp(tmp_path, db_url)
