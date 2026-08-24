"""Defect 3.1 (v0.2.1) — the MCP dependency-contract acceptance matrix.

The declared range is ``mcp>=1.28,<3``: two SDK majors with one breaking
rename between them. The public claim is only honest if BOTH majors are
proven end-to-end from a built wheel in clean virtualenvs — version check,
full stdio lifecycle, authenticated Streamable HTTP round trip + 401
refusal, non-loopback bind refusal, and a recorded installed ``mcp`` version
that must equal the pin.

This test delegates to :mod:`scripts.mcp_acceptance_matrix`, which performs
the whole matrix and fails on any phase failure or version mismatch. Like
the wheel test it requires network access to build/install, so offline
sandboxes skip it; CI runs it as a required job (also serving as the
Dependabot mcp-widening guard).
"""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.release]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "mcp_acceptance_matrix.py"


def _network_available() -> bool:
    """True when PyPI is reachable (clean-venv installs need it)."""
    try:
        with socket.create_connection(("pypi.org", 443), timeout=3):
            return True
    except OSError:
        return False


@pytest.mark.skipif(
    not _network_available(),
    reason="acceptance matrix needs PyPI for isolated builds + clean venvs",
)
def test_mcp_dependency_matrix_both_majors(tmp_path: Path) -> None:
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(_SCRIPT), "--keep"],
        capture_output=True,
        text=True,
        timeout=2400,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, (
        f"MCP acceptance matrix FAILED:\n{result.stdout[-4000:]}\n{result.stderr[-2000:]}"
    )
    # Every intended cell must have been attempted and passed.
    out = result.stdout
    assert "mcp==1." in out or "mcp==2." in out, f"no matrix cells ran:\n{out[-1000:]}"
    assert "ALL CELLS PASS" in out, f"matrix did not complete:\n{out[-2000:]}"
