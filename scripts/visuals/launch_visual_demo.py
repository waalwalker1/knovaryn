#!/usr/bin/env python3
"""Start the Knovaryn REST server + web console against a prepared workspace.

The server resolves its store from the working directory (default
``./.knovaryn/knovaryn.db``), so the demo workspace is used as the child
process's CWD — the console then shows exactly the project, examples,
lineage, and version that prepare_demo_state.py persisted.

Standalone use (blocks until Ctrl-C):

    uv run --no-sync python scripts/visuals/launch_visual_demo.py \
        --workspace /tmp/knovaryn-visual-xxxx [--port 8970]

capture_docs_screenshots.py imports :func:`start_server` /
:func:`wait_for_health` to manage the lifecycle itself.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PORT = 8970


def _cli() -> list[str]:
    """Resolve the knovaryn CLI.

    Order: $KNOVARYN_CLI (explicit override), the venv the current
    interpreter runs from, the project checkout's .venv, then $PATH. The
    override exists for checkouts on network-synced filesystems, where a
    local venv (fast imports) can be pointed at while the scripts stay in
    the synced tree.
    """
    override = os.environ.get("KNOVARYN_CLI")
    if override:
        return [override]
    in_venv = Path(sys.prefix) / "bin" / "knovaryn"
    if in_venv.exists():
        return [str(in_venv)]
    candidate = REPO_ROOT / ".venv" / "bin" / "knovaryn"
    if candidate.exists():
        return [str(candidate)]
    found = shutil.which("knovaryn")
    if found:
        return [found]
    raise SystemExit("knovaryn CLI not found — run inside the project venv")


def start_server(workspace: Path, port: int = DEFAULT_PORT) -> subprocess.Popen:
    """Start `knovaryn server` bound to loopback with the workspace as CWD."""
    cmd = _cli() + ["server", "--host", "127.0.0.1", "--port", str(port)]
    return subprocess.Popen(
        cmd,
        cwd=workspace,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_for_health(port: int = DEFAULT_PORT, timeout: float = 300.0) -> bool:
    """Poll /v1/health until it answers 2xx (or time out).

    The generous default absorbs slow first starts — on network-synced
    checkouts (cloud-drive-backed venvs) interpreter startup can stall for
    minutes while module files hydrate.
    """
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/v1/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if 200 <= resp.status < 300:
                    return True
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            pass
        time.sleep(0.4)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    state_file = args.workspace / "state.json"
    if not state_file.exists():
        raise SystemExit(f"no state.json in {args.workspace} — run prepare_demo_state.py first")
    state = json.loads(state_file.read_text())

    proc = start_server(args.workspace, args.port)
    if not wait_for_health(args.port):
        proc.terminate()
        raise SystemExit(f"server did not become healthy on port {args.port}")
    print(
        f"console: http://127.0.0.1:{args.port}/  (project {state['project_id']}); Ctrl-C to stop",
        file=sys.stderr,
    )
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
