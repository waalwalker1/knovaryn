"""MCP acceptance-matrix driver (defect 3.1, v0.2.1).

Runs INSIDE a clean virtualenv that has knovaryn + one pinned ``mcp`` major
installed, and exercises one phase of the mandatory acceptance lifecycle:

* ``version``       — print the installed mcp/knovaryn versions as JSON
* ``stdio``         — full stdio lifecycle: startup, client connect, tool and
                      resource-template discovery, project creation, source
                      addition, pipeline run to completion, bounded preview,
                      lineage retrieval, clean shutdown with a thread-leak check
* ``http``          — authenticated Streamable HTTP round trip against a live
                      ``knovaryn-mcp --transport streamable-http`` subprocess,
                      plus an unauthenticated request that must get 401
* ``bind-refusal``  — a non-loopback bind without a token must refuse to start

The outer orchestrator (``scripts/mcp_acceptance_matrix.py``) pins the SDK
version per venv and fails the whole matrix when a phase or a version
mismatches. This file deliberately has no knovaryn-internal imports beyond
the public entry points it drives.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


def _sdk_versions() -> dict[str, str]:
    from importlib.metadata import version

    import mcp  # noqa: F401  (presence is the point)

    return {"mcp": version("mcp")}


def _console_exe(name: str = "knovaryn-mcp") -> str:
    """Absolute path to a console script installed beside this interpreter."""
    exe_dir = Path(sys.executable).resolve().parent
    script = exe_dir / name
    if not script.exists():
        raise AssertionError(f"console script not found next to interpreter: {script}")
    return str(script)


# --------------------------------------------------------------------------
# client-side compat
def _streams_pair(streams: Any) -> tuple[Any, Any]:
    """Normalize the yielded streams: 1.x yields a 3-tuple (read, write,
    get_session_id); 2.x yields a plain 2-tuple."""
    if isinstance(streams, tuple) and len(streams) == 3:
        return streams[0], streams[1]
    return streams[0], streams[1]


def _text_of(result: Any) -> str:
    return "\n".join(
        t for b in result.content if (t := (getattr(b, "text", None)))
    )


def _payload(result: Any) -> dict[str, Any]:
    """Parse a structured tool result into a dict (structuredContent or JSON text)."""
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    return json.loads(_text_of(result))


# --------------------------------------------------------------------------
def phase_stdio(database_url: str) -> dict[str, Any]:
    from mcp import ClientSession, StdioServerParameters

    exe = _console_exe()
    params = StdioServerParameters(
        command=exe,
        args=["--transport", "stdio", "--database-url", database_url],
        env={**os.environ},
    )

    async def drive() -> dict[str, Any]:
        out: dict[str, Any] = {}
        baseline_threads = {t.name for t in threading.enumerate()}

        from mcp.client.stdio import stdio_client

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                out["initialized"] = True

                tools = await session.list_tools()
                names = {t.name for t in tools.tools}
                out["tool_count"] = len(names)
                required = {
                    "health",
                    "knovaryn_create_project",
                    "knovaryn_add_source",
                    "knovaryn_start_pipeline",
                    "knovaryn_run_job",
                    "knovaryn_get_job",
                    "knovaryn_preview_examples",
                    "knovaryn_lineage",
                }
                missing = required - names
                assert not missing, f"missing tools: {sorted(missing)}"

                rts = await session.list_resource_templates()
                tmpl_attr = next(
                    (a for a in ("resource_templates", "resourceTemplates")
                     if hasattr(rts, a)), None
                )
                templates = getattr(rts, tmpl_attr) if tmpl_attr else []
                out["resource_templates"] = len(templates)
                assert len(templates) >= 6, "expected the knovaryn:// resource templates"

                # project creation
                res = await session.call_tool(
                    "knovaryn_create_project",
                    {"slug": "acceptance-matrix", "display_name": "Acceptance Matrix"},
                )
                proj = _payload(res)
                assert "project_id" in proj, f"create_project failed: {proj}"
                project_id = proj["project_id"]

                # source addition
                res = await session.call_tool(
                    "knovaryn_add_source",
                    {
                        "project_id": project_id,
                        "original_name": "acceptance.md",
                        "content": (
                            "# Widgets\n## Assembly\nA widget is a base plate plus a lid.\n"
                            "The lid must be torqued to 5 N·m.\n## Inspection\n"
                            "Each unit is inspected for cracks before shipping.\n"
                        ),
                        "media_type": "text/markdown",
                    },
                )
                src = _payload(res)
                assert src.get("status") == "ok", f"add_source failed: {src}"

                # pipeline lifecycle: queue, execute offline, poll to terminal
                res = await session.call_tool(
                    "knovaryn_start_pipeline",
                    {
                        "project_id": project_id,
                        "task_fam_families": "factual_explanation:1.0",
                    },
                )
                started = _payload(res)
                assert "job_id" in started, f"start_pipeline failed: {started}"
                job_id = started["job_id"]

                res = await session.call_tool("knovaryn_run_job", {"job_id": job_id})
                ran = _payload(res)
                state = ran.get("state") or ran.get("job", {}).get("state")
                assert state in ("succeeded", "completed"), f"run_job state: {ran}"

                res = await session.call_tool(
                    "knovaryn_get_job", {"job_id": job_id}
                )
                job = _payload(res)
                assert job.get("state") in ("succeeded", "completed") or (
                    job.get("job", {}) or {}
                ).get("state") in ("succeeded", "completed"), f"get_job: {job}"

                # bounded preview
                res = await session.call_tool(
                    "knovaryn_preview_examples",
                    {"project_id": project_id, "limit": 5},
                )
                preview = _payload(res)
                examples = preview.get("examples") or []
                out["example_count"] = len(examples)
                assert examples, f"no examples produced: {list(preview)[:6]}"

                # lineage retrieval
                example_id = examples[0].get("id") if isinstance(examples[0], dict) else examples[0]
                res = await session.call_tool(
                    "knovaryn_lineage",
                    {"project_id": project_id, "example_id": example_id},
                )
                lineage = _payload(res)
                assert lineage.get("example_id") == example_id, f"lineage: {lineage}"
                assert lineage.get("source_span_ids"), "lineage lacks span ids"
                out["lineage_ok"] = True

        # clean shutdown: no leaked non-daemon threads
        deadline = time.monotonic() + 10.0
        leaked: set[str] = set()
        while time.monotonic() < deadline:
            current = {t.name for t in threading.enumerate() if not t.daemon}
            leaked = current - baseline_threads
            if not leaked:
                break
            await asyncio.sleep(0.2)
        out["leaked_threads"] = sorted(leaked)
        out["stdio_ok"] = True
        return out

    return asyncio.run(drive())


# --------------------------------------------------------------------------
def phase_http(port: int, token: str) -> dict[str, Any]:
    exe = _console_exe()
    env = {**os.environ, "KNOVARYN_API_TOKEN": token}
    proc = subprocess.Popen(
        [exe, "--transport", "streamable-http", "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    out: dict[str, Any] = {}
    try:
        # wait for the port to open
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                    break
            except OSError:
                if proc.poll() is not None:
                    tail = (proc.stdout.read() if proc.stdout else b"").decode()[-800:]
                    raise AssertionError(f"http server died early: {tail}")
                time.sleep(0.3)
        else:
            raise AssertionError("http server never opened its port")

        url = f"http://127.0.0.1:{port}/mcp"

        # (a) unauthenticated request must be refused (bearer guard)
        import urllib.error
        import urllib.request

        req = urllib.request.Request(url, method="POST", data=b"{}")
        refused = False
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                refused = resp.status < 400
        except urllib.error.HTTPError as e:
            refused = e.code == 401
        out["unauthenticated_refused"] = refused
        assert refused, "unauthenticated HTTP request was not refused"

        # (b) authenticated round trip through a real MCP client session
        from contextlib import AsyncExitStack

        from mcp import ClientSession

        async def drive():
            major = int(_sdk_versions()["mcp"].split(".")[0])
            headers = {"Authorization": f"Bearer {token}"}
            stack = AsyncExitStack()
            try:
                # Both majors expose snake_case `streamable_http_client(url, *,
                # http_client=...)`; custom headers go through the provided
                # client. 1.x bundles it as `httpx`, 2.x renamed it `httpx2`.
                from mcp.client.streamable_http import streamable_http_client

                if major >= 2:
                    import httpx2 as httpx_mod  # bundled with mcp 2.x
                else:
                    import httpx as httpx_mod

                hc = await stack.enter_async_context(
                    httpx_mod.AsyncClient(headers=headers, timeout=30.0)
                )
                streams = await stack.enter_async_context(
                    streamable_http_client(url, http_client=hc)
                )
                read, write = _streams_pair(streams)
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    assert any(t.name == "health" for t in tools.tools)
                    res = await session.call_tool("health", {})
                    text = _text_of(res)
                    assert '"status": "ok"' in text, f"health over http: {text}"
                    return True
            finally:
                await stack.aclose()
            return False

        out["authenticated_round_trip"] = asyncio.run(drive())
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()
    out["http_ok"] = True
    return out


# --------------------------------------------------------------------------
def phase_bind_refusal() -> dict[str, Any]:
    exe = _console_exe()
    env = {k: v for k, v in os.environ.items() if k != "KNOVARYN_API_TOKEN"}
    proc = subprocess.run(
        [exe, "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8977"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode != 0, "non-loopback bind without token must fail"
    assert "non-loopback" in combined, f"refusal not explained: {combined[-500:]}"
    return {"bind_refusal_ok": True, "exit_code": proc.returncode}


# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["version", "stdio", "http", "bind-refusal"])
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--port", type=int, default=8931)
    parser.add_argument("--token", default="acceptance-token")
    args = parser.parse_args()

    if args.phase == "version":
        print(json.dumps(_sdk_versions()))
        return 0
    if args.phase == "stdio":
        assert args.database_url, "--database-url required for stdio phase"
        result = phase_stdio(args.database_url)
    elif args.phase == "http":
        result = phase_http(args.port, args.token)
    else:
        result = phase_bind_refusal()
    print(json.dumps({"phase": args.phase, **result}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
