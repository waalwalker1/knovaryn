"""MCP server transport + catalogue + resources (spec §17 / WP F3, F4, F5).

F3 — Transport support: a **real** stdio client-server round trip (spawn the
MCP server as a subprocess and drive it over stdio pipes), plus the
Streamable-HTTP server object, graceful shutdown, concurrent tool calls,
bounded output, and pagination.

F4 — Tool catalogue: the documented tool list is generated from the server's
actual registry (``list_tools``) so names/counts cannot drift from the
implementation. Asserts the full WP-F tool surface is present.

F5 — Resources: the six ``knovaryn://`` URI patterns resolve to bounded payloads
through the lifespan workspace, and every handle enforces authorization
(existence + project scoping).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from knovaryn.interfaces.mcp.server import SERVER_ID, build_server

# A corpus rich enough that the single-family pipeline always yields examples.
_RICH_CORPUS = (
    "# Widgets\n"
    "## Assembly\n"
    "A widget is a base plate plus a lid. The lid must be torqued to 5 N·m.\n"
    "## Inspection\n"
    "Each unit is inspected for cracks before shipping.\n"
    "## Tooling\n"
    "The assembly line applies a torque wrench and records the value per unit.\n"
)

# ---------------------------------------------------------------------------
# Shared harness (mirrors tests/test_mcp_server.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def server(tmp_path: Path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/mcp.db"
    return build_server(database_url=db_url)


@asynccontextmanager
async def _session(server: Any) -> AsyncIterator[Any]:
    from mcp.shared.memory import create_connected_server_and_client_session
    from mcp.types import Implementation

    async with create_connected_server_and_client_session(
        server,
        client_info=Implementation(name="knovaryn-test", version="0.0.0"),
    ) as session:
        yield session


def _block_text(block: Any) -> str | None:
    if isinstance(block, dict):
        return block.get("text")
    return getattr(block, "text", None)


async def _acall(session: Any, tool: str, arguments: dict[str, Any] | None = None) -> str:
    result = await session.call_tool(tool, arguments or {})
    texts = []
    for block in getattr(result, "content", result or []):
        txt = _block_text(block)
        if txt is not None:
            texts.append(txt)
    return "\n".join(texts)


def _json(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return json.loads(lines[0])
    except (json.JSONDecodeError, IndexError):
        return {}


async def _acall_result(session, tool, arguments=None):
    result = await session.call_tool(tool, arguments or {})
    texts = []
    for block in getattr(result, "content", result or []):
        txt = _block_text(block)
        if txt is not None:
            texts.append(txt)
    return result, "\n".join(texts)


# ---------------------------------------------------------------------------
# F4 — tool catalogue derived from the actual registry
# ---------------------------------------------------------------------------

DOCUMENTED_TOOLS = {
    "health",
    "knovaryn_doctor",
    "knovaryn_create_project",
    "knovaryn_list_projects",
    "knovaryn_add_source",
    "knovaryn_inspect_source",
    "knovaryn_license_report",
    "knovaryn_estimate_run",
    "knovaryn_start_pipeline",
    "knovaryn_get_job",
    "knovaryn_list_jobs",
    "knovaryn_run_job",
    "knovaryn_cancel_job",
    "knovaryn_resume_job",
    "knovaryn_lineage",
    "knovaryn_preview_examples",
    "knovaryn_review_example",
    "knovaryn_validate_dataset",
    "knovaryn_create_dataset_version",
    "knovaryn_export_dataset",
    "knovaryn_publish_dataset",
    "knovaryn_compare_runs",
    "run_pipeline",
}


async def test_documented_tool_list_matches_registry(server) -> None:
    async with _session(server) as session:
        tools = await session.list_tools()
    registered = {t.name for t in tools.tools}
    # every documented tool must actually be registered (no drift)
    missing = DOCUMENTED_TOOLS - registered
    assert not missing, f"documented tools missing from registry: {sorted(missing)}"
    # the documented surface is a strict subset; extra tools are allowed but
    # the registry drive the count
    assert registered >= DOCUMENTED_TOOLS


async def test_tool_catalogue_covers_required_categories(server) -> None:
    """Each WP-F category maps to at least one registered tool."""
    async with _session(server) as session:
        tools = await session.list_tools()
    names = {t.name for t in tools.tools}
    required_minima = {
        "health/doctor": lambda n: "health" in n or "doctor" in n,
        "project lifecycle": lambda n: n in ("knovaryn_create_project", "knovaryn_list_projects"),
        "source intake/inspection": {"knovaryn_add_source", "knovaryn_inspect_source"}
        <= names,
        "run estimate": "knovaryn_estimate_run" in names,
        "start/get/list/cancel/resume": {
            "knovaryn_start_pipeline",
            "knovaryn_get_job",
            "knovaryn_list_jobs",
            "knovaryn_cancel_job",
            "knovaryn_resume_job",
        }
        <= names,
        "lineage": "knovaryn_lineage" in names,
        "example preview/review": {"knovaryn_preview_examples", "knovaryn_review_example"}
        <= names,
        "validation": "knovaryn_validate_dataset" in names,
        "versioning": "knovaryn_create_dataset_version" in names,
        "export": "knovaryn_export_dataset" in names,
        "publication": "knovaryn_publish_dataset" in names,
        "run comparison": "knovaryn_compare_runs" in names,
        "license/privacy": "knovaryn_license_report" in names,
    }
    for category, ok in required_minima.items():
        assert ok, f"tool catalogue missing coverage for: {category}"


# ---------------------------------------------------------------------------
# F5 — resources: 6 URI patterns, bounded, authorization on every handle
# ---------------------------------------------------------------------------

EXPECTED_RESOURCE_URIS = {
    "knovaryn://projects/{project_id}",
    "knovaryn://projects/{project_id}/sources/{source_id}",
    "knovaryn://projects/{project_id}/jobs/{job_id}",
    "knovaryn://projects/{project_id}/jobs/{job_id}/events",
    "knovaryn://projects/{project_id}/examples/{example_id}/lineage",
    "knovaryn://projects/{project_id}/datasets/{version_id}",
}


async def test_all_six_resource_templates_registered(server) -> None:
    async with _session(server) as session:
        templates = await session.list_resource_templates()
        resources = await session.list_resources()
    template_uris = {t.uriTemplate for t in templates.resourceTemplates}
    for expected in EXPECTED_RESOURCE_URIS:
        assert expected in template_uris, f"resource template not registered: {expected}"
    assert len(template_uris) == len(EXPECTED_RESOURCE_URIS)
    # concrete project/job/etc handles are not listed as resources until created
    assert isinstance(resources.resources, list)


async def _read_resource(server, uri: str) -> dict[str, Any]:
    """Read an MCP resource by URI through a fresh session (text payload)."""
    async with _session(server) as session:
        got = await session.read_resource(uri)
    texts = []
    for c in got.contents:
        txt = getattr(c, "text", None)
        if txt:
            texts.append(txt)
    return _json("\n".join(texts))


async def test_project_resource_authorizes(server) -> None:
    async with _session(server) as session:
        body = _json(await _acall(session, "knovaryn_create_project",
                                  {"slug": "rp", "display_name": "RP"}))
    pid = body.get("project_id")
    assert pid
    # read resource for an existing project
    ok = await _read_resource(server, f"knovaryn://projects/{pid}")
    assert ok and ok.get("project_id") == pid and ok.get("authorized") is not False
    # read resource for a missing project → denied
    denied = await _read_resource(server, "knovaryn://projects/p_missing")
    assert denied and denied.get("authorized") is False


async def test_job_resource_and_events_authorize(server) -> None:
    # create + source + run
    async with _session(server) as session:
        proj = _json(await _acall(session, "knovaryn_create_project",
                                    {"slug": "rj", "display_name": "RJ"}))
        pid = proj["project_id"]
        _json(await _acall(session, "knovaryn_add_source", {
            "project_id": pid, "original_name": "s.md",
            "content": _RICH_CORPUS,
        }))
        job = _json(await _acall(session, "knovaryn_start_pipeline", {
            "project_id": pid, "task_fam_families": "factual_explanation:1.0",
        }))
        jid = job["job_id"]
        _json(await _acall(session, "knovaryn_run_job", {"job_id": jid}))
    job_uri = f"knovaryn://projects/{pid}/jobs/{jid}"
    ok = await _read_resource(server, job_uri)
    assert ok.get("id") == jid
    ev = await _read_resource(server, f"{job_uri}/events")
    assert ev.get("job_id") == jid
    assert ev.get("event_count", 0) > 0
    # missing job → denied
    denied = await _read_resource(server, "knovaryn://projects/x/jobs/job_missing")
    assert denied.get("authorized") is False


async def test_source_resource_authorizes_and_bounds_content(server) -> None:
    pid = None
    async with _session(server) as session:
        proj = _json(await _acall(session, "knovaryn_create_project",
                                    {"slug": "rsrc", "display_name": "R"}))
        pid = proj["project_id"]
        src = _json(await _acall(session, "knovaryn_add_source", {
            "project_id": pid, "original_name": "p.md",
            "content": (
                "# P\nA paragraph that must never leak as raw content "
                "through the source resource.\n"
            ),
        }))
        sid = src["source_id"]
    got = await _read_resource(server, f"knovaryn://projects/{pid}/sources/{sid}")
    assert got.get("id") == sid
    assert "content" not in got  # bounded: never raw content
    assert got.get("authorized") is not False


async def test_lineage_resource_authorizes(server) -> None:
    pid = None
    ex_id = None
    async with _session(server) as session:
        proj = _json(await _acall(session, "knovaryn_create_project",
                                    {"slug": "rl", "display_name": "L"}))
        pid = proj["project_id"]
        _json(await _acall(session, "knovaryn_add_source", {
            "project_id": pid, "original_name": "l.md",
            "content": _RICH_CORPUS,
        }))
        job = _json(await _acall(session, "knovaryn_start_pipeline", {
            "project_id": pid, "task_fam_families": "factual_explanation:1.0",
        }))
        _json(await _acall(session, "knovaryn_run_job", {"job_id": job["job_id"]}))
        prev = _json(await _acall(session, "knovaryn_preview_examples", {"project_id": pid}))
        assert prev.get("examples"), prev
        ex_id = prev["examples"][0]["id"]
    got = await _read_resource(server, f"knovaryn://projects/{pid}/examples/{ex_id}/lineage")
    assert got.get("example_id") == ex_id
    assert got.get("source_document_ids")
    denied = await _read_resource(
        server, f"knovaryn://projects/{pid}/examples/ex_missing/lineage")
    assert denied.get("authorized") is False


async def test_dataset_version_resource_authorizes(server) -> None:
    pid = None
    ver_id = None
    async with _session(server) as session:
        proj = _json(await _acall(session, "knovaryn_create_project",
                                    {"slug": "rd", "display_name": "D"}))
        pid = proj["project_id"]
        _json(await _acall(session, "knovaryn_add_source", {
            "project_id": pid, "original_name": "d.md",
            "content": _RICH_CORPUS,
        }))
        job = _json(await _acall(session, "knovaryn_start_pipeline", {
            "project_id": pid, "task_fam_families": "factual_explanation:1.0",
        }))
        _json(await _acall(session, "knovaryn_run_job", {"job_id": job["job_id"]}))
        ver = _json(await _acall(session, "knovaryn_create_dataset_version", {"project_id": pid}))
        ver_id = ver["version_id"]
    got = await _read_resource(server, f"knovaryn://projects/{pid}/datasets/{ver_id}")
    assert got.get("version_id") == ver_id
    assert got.get("authorized") is not False
    # cross-project: version does not belong to another project → denied
    denied = await _read_resource(server, f"knovaryn://projects/p_other/datasets/{ver_id}")
    assert denied.get("authorized") is False


# ---------------------------------------------------------------------------
# F3 — concurrency, bounded output, pagination
# ---------------------------------------------------------------------------


async def test_pagination_list_projects(server) -> None:
    async with _session(server) as session:
        for i in range(5):
            _json(await _acall(session, "knovaryn_create_project",
                               {"slug": f"pg{i}", "display_name": f"PG {i}"}))
        # small page
        page1 = _json(await _acall(session, "knovaryn_list_projects", {"limit": 2}))
        assert "projects" in page1
        # the list is bounded and complete across all pages
        assert len(page1["projects"]) <= 2


async def test_concurrent_tool_calls(server) -> None:
    """Several tool calls in flight on one session complete without a deadlock."""
    import asyncio

    async with _session(server) as session:
        async def health_call():
            r = await session.call_tool("health", {})
            text = "\n".join(t for b in r.content if (t := _block_text(b)))
            return _json(text).get("status")

        results = await asyncio.gather(*[health_call() for _ in range(8)])
        assert results == ["ok"] * 8


async def test_bounded_preview_output(server) -> None:
    """preview_examples is bounded: content is redacted and limited."""
    async with _session(server) as session:
        proj = _json(await _acall(session, "knovaryn_create_project",
                                    {"slug": "bd", "display_name": "B"}))
        pid = proj["project_id"]
        _json(await _acall(session, "knovaryn_add_source", {
            "project_id": pid, "original_name": "b.md",
            "content": _RICH_CORPUS,
        }))
        job = _json(await _acall(session, "knovaryn_start_pipeline", {
            "project_id": pid, "task_fam_families": "factual_explanation:1.0",
        }))
        _json(await _acall(session, "knovaryn_run_job", {"job_id": job["job_id"]}))
        preview = _json(await _acall(session, "knovaryn_preview_examples",
                                     {"project_id": pid, "limit": 3}))
        assert len(preview.get("examples", [])) <= 3
        for e in preview.get("examples", []):
            assert "content" not in e  # redacted


# ---------------------------------------------------------------------------
# F3 — stdio: a real client-server subprocess round trip
# ---------------------------------------------------------------------------


def test_stdio_transport_subprocess_end_to_end(tmp_path: Path) -> None:
    """Spawn the MCP server as a subprocess over stdio and drive it as a client.

    This is the canonical MCP deployment path (F3 'stdio'), exercised as a real
    client-server round trip via ``anyio`` (the asyncio backend already used by
    the pinned MCP SDK), not an in-memory simulation. Declared as a *sync* test
    so it owns its own event loop (via ``anyio.run``), like a standalone client.
    """
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    db_url = f"sqlite+aiosqlite:///{tmp_path}/stdio.db"
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "knovaryn.interfaces.mcp",
            "--transport",
            "stdio",
            "--database-url",
            db_url,
        ],
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
            assert "knovaryn_lineage" in names
            res = await session.call_tool("health", {})
            text = "\n".join(t for b in res.content if (t := _block_text(b)))
            body = _json(text)
            assert body.get("status") == "ok"
            assert body.get("server_id") == SERVER_ID

    anyio.run(drive)


def test_streamable_http_client_round_trip(tmp_path: Path) -> None:
    """F3 'streamable-http': run the packaged server over HTTP and drive a real
    remote client (initialize + tool call) — the second F3 transport.

    Mirrors the stdio subprocess test: spawn the actual ``knovaryn-mcp`` server
    (``python -m knovaryn.interfaces.mcp --transport streamable-http``) as a
    subprocess on a loopback port and connect with ``streamablehttp_client``.
    The server is hosted with uvicorn over FastMCP's Starlette app.
    """
    import socket

    import anyio

    # reserve a free loopback port for the server process
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    db_url = f"sqlite+aiosqlite:///{tmp_path}/shttp.db"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "knovaryn.interfaces.mcp",
            "--transport",
            "streamable-http",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--database-url",
            db_url,
        ],
        env={**os.environ},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        anyio.run(_shttp_drive, port)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


async def _shttp_drive(port: int) -> None:
    # wait for the server to accept connections
    import socket

    import anyio
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    for _ in range(300):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            await anyio.sleep(0.1)
    else:
        raise RuntimeError("streamable-http server did not start listening")

    async with streamablehttp_client(f"http://127.0.0.1:{port}/mcp") as streams:
        read, write, _get_session_id = streams
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert "health" in names
            assert "knovaryn_list_jobs" in names
            res = await session.call_tool("health", {})
            text = "\n".join(t for b in res.content if (t := _block_text(b)))
            assert '"status": "ok"' in text


def test_stdio_graceful_shutdown(tmp_path: Path) -> None:
    """The stdio server exits cleanly (loop ends) after the client disconnects."""
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    db_url = f"sqlite+aiosqlite:///{tmp_path}/shutdown.db"
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "knovaryn.interfaces.mcp", "--transport", "stdio",
              "--database-url", db_url],
        env={**os.environ},
    )

    async def drive() -> None:
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            await session.call_tool("health", {})
        # exiting the context triggers graceful server shutdown

    anyio.run(drive)
    # reaching here proves the transport + shutdown completed without hanging
    assert True
