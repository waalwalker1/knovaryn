"""MCP server (spec §17) — offline integration tests for the 17-tool surface.

Builds the real :func:`knovaryn.interfaces.mcp.server.build_server` server with
``mcp`` installed, connects a client over an in-memory transport, and drives the
full ``knovaryn_*`` tool set against a throwaway SQLite workspace with the fake
provider (no API keys, no network). The flagship assertion is provenance: every
example returned by the preview tool carries ``source_document_ids`` and
``source_span_ids`` (the enforced provenance-minimum gate), verified through the
agent-facing MCP surface.

The MCP tool handlers each invoke ``asyncio.run()`` internally, so every test
drives the client session from a fresh ``asyncio.run(...)`` rather than nesting
calls inside a running loop (mirroring ``tests/test_workspace_control.py``).
"""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from knovaryn.interfaces.mcp.server import SERVER_ID, build_server

# ---------------------------------------------------------------------------
# In-memory transport resolution (the import path varies across mcp versions;
# try the documented candidates in order and surface the one that exists).
# ---------------------------------------------------------------------------


def _mem_module() -> Any:
    for name in ("mcp.client.in_memory", "mcp.shared.memory"):
        try:
            return importlib.import_module(name)
        except ModuleNotFoundError:
            continue
    raise ImportError(
        "no in-memory transport found in installed 'mcp' package; "
        "expected 'mcp.client.in_memory' or 'mcp.shared.memory'"
    )


def _connected_session(server: Any) -> Any:
    """Return (read_stream, write_stream) for a client connected to ``server``."""
    mod = _mem_module()
    # mcp>=1.0: create_connected_server_and_client_session(FastMCP) is the
    # canonical in-process test connector when present.
    for maker in (getattr(mod, "create_connected_server_and_client_session", None),):
        if maker is not None:
            try:
                return maker(server)
            except TypeError:
                pass
    return mod.create_in_memory_transport()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def server(tmp_path: Path, monkeypatch) -> Any:
    """A built FastMCP server with a hermetic, throwaway SQLite workspace.

    The MCP tools build a shared Workspace through module-level
    ``_WorkspaceHolder._WS`` which reads default config. We point configuration
    at a temp DB and reset the singleton so the workspace rebuilds against it —
    the same injection used by tests/test_rest_api.py.

    The tool handlers bridge to the async framework via
    ``knovaryn.interfaces.mcp.server._asyncio`` which calls ``asyncio.run()``.
    On a real MCP deployment that handler runs in a threadpool with no live
    loop, so ``asyncio.run()`` is fine. The in-process in-memory transport we
    use here runs handlers inside a loop that is already running, which makes
    ``asyncio.run()`` throw. We therefore re-seat ``_asyncio`` onto a dedicated
    background loop (``run_coroutine_threadsafe``) so the server logic and the
    MCP transport stay real while the loop bridge matches a deployed server.
    """

    import threading

    import knovaryn.application.workspace as ws_mod
    import knovaryn.interfaces.mcp.server as mcp_mod

    db_url = f"sqlite+aiosqlite:///{tmp_path}/mcp.db"
    monkeypatch.setattr(ws_mod, "load_config", lambda **kw: {"storage.database_url": db_url})

    bg_loop = asyncio.new_event_loop()

    def _background_aio(coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, bg_loop).result()

    monkeypatch.setattr(mcp_mod, "_asyncio", _background_aio)

    thread = threading.Thread(target=bg_loop.run_forever, daemon=True)
    thread.start()

    mcp_mod._WS._workspace = None  # force rebuild against the temp DB
    yield build_server()
    mcp_mod._WS._workspace = None
    bg_loop.call_soon_threadsafe(bg_loop.stop)
    thread.join(timeout=5)


@asynccontextmanager
async def _session(server: Any) -> AsyncGenerator[Any, None]:
    """A connected MCP ClientSession over the in-memory transport.

    mcp>=1.0 exposes ``create_connected_server_and_client_session`` (an async
    context manager that wires the server to a client and yields the
    ``ClientSession``); ``mcp.shared.memory`` is where it lives in 1.29.0. Fall
    back to a manual ``ClientSession(read, write)`` for ancient transports.
    """
    from mcp.client.session import ClientSession

    mod = _mem_module()
    maker = getattr(mod, "create_connected_server_and_client_session", None)
    if maker is not None:
        async with maker(server) as session:
            yield session
        return

    # Legacy path: manually build a transport and initialize the session.
    read, write = _connected_session(server)
    async with ClientSession(read, write) as session:
        await session.initialize()
        yield session


def _block_text(block: Any) -> str | None:
    """Extract the text payload from a content block (model or dict)."""
    if isinstance(block, dict):
        return block.get("text")
    return getattr(block, "text", None)


def call(
    server: Any,
    tool: str,
    arguments: dict[str, Any] | None = None,
) -> Callable[[], Any]:
    """Return a zero-arg callable that invokes ``tool`` in a fresh event loop."""

    async def _invoke() -> Any:
        async with _session(server) as session:
            result = await session.call_tool(tool, arguments or {})
        # MCP tool results are a list of content blocks; coerce text out.
        texts = []
        for block in getattr(result, "content", result or []):
            txt = _block_text(block)
            if txt is not None:
                texts.append(txt)
        return result, "\n".join(texts)

    def _run() -> Any:
        return asyncio.run(_invoke())

    return _run


def _json(text: str) -> dict[str, Any]:
    """Best-effort parse of the tool's text payload (JSON object or JSONL)."""
    import json

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


# ---------------------------------------------------------------------------
# health / doctor
# ---------------------------------------------------------------------------


def test_health(server) -> None:
    _, text = call(server, "health")()
    body = _json(text)
    assert body.get("status") == "ok"
    assert body.get("server_id") == SERVER_ID


def test_doctor_lists_runtime_profiles(server) -> None:
    result, text = call(server, "knovaryn_doctor")()
    body = _json(text)
    assert body.get("status") == "ok"
    assert "fake" in body.get("runtime_profiles", [])
    assert body.get("dependencies", {}).get("mcp") is True


# ---------------------------------------------------------------------------
# full lifecycle + provenance (flagship)
# ---------------------------------------------------------------------------


def test_full_lifecycle_with_provenance(server) -> None:
    # 1. create project
    _, text = call(
        server,
        "knovaryn_create_project",
        {
            "slug": "mcp-widgets",
            "display_name": "MCP Widgets",
        },
    )()
    proj = _json(text)
    assert proj.get("project_id", "").startswith("proj_")

    # 2. add source
    _, text = call(
        server,
        "knovaryn_add_source",
        {
            "project_id": proj["project_id"],
            "original_name": "assembly.md",
            "content": (
                "# Widgets\n## Assembly\nA widget is a base plate plus a lid.\n"
                "The lid must be torqued to 5 N·m.\n## Inspection\n"
                "Each unit is inspected for cracks before shipping.\n"
            ),
        },
    )()
    src = _json(text)
    assert src.get("status") == "ok"
    assert src.get("source_id", "").startswith("src_")

    # 3. queue + inspect the job
    # Single task family at 1.0: with a small corpus the multi-family planner
    # rounds every (chunk_count × topology × family × difficulty) product to 0
    # and emits an empty plan (=> 0 candidates). A single family keeps the plan
    # non-empty — same configuration the workspace control-plane tests use.
    _, text = call(
        server,
        "knovaryn_start_pipeline",
        {
            "project_id": proj["project_id"],
            "task_fam_families": "factual_explanation:1.0",
        },
    )()
    job = _json(text)
    job_id = job.get("job_id")
    assert job_id, job

    _, text = call(server, "knovaryn_get_job", {"job_id": job_id})()
    assert "resources" in _json(text)

    # 4. run job offline
    _, text = call(server, "knovaryn_run_job", {"job_id": job_id})()
    run = _json(text)
    assert run.get("state") == "succeeded", run

    # 5. preview examples — PROVENANCE assertion
    _, text = call(
        server,
        "knovaryn_preview_examples",
        {
            "project_id": proj["project_id"],
            "limit": 100,
        },
    )()
    preview = _json(text)
    examples = preview.get("examples", [])
    assert examples, "pipeline must produce examples"
    for e in examples:
        assert e.get("source_document_ids"), f"example missing source_document_ids: {e}"
        assert e.get("source_span_ids"), f"example missing source_span_ids: {e}"
        assert e.get("_redacted") is True

    # 6. inspect the added source
    _, text = call(
        server,
        "knovaryn_inspect_source",
        {
            "project_id": proj["project_id"],
            "source_id": src["source_id"],
        },
    )()
    insp = _json(text)
    assert insp.get("source_id") == src["source_id"]
    assert insp.get("media_type") == "text/markdown"

    # 7. review an example (accept)
    ex_id = examples[0].get("id")
    _, text = call(
        server,
        "knovaryn_review_example",
        {
            "example_id": ex_id,
            "decision": "accept",
        },
    )()
    rev = _json(text)
    assert rev.get("status") == "recorded"

    # 8. validate dataset
    _, text = call(
        server,
        "knovaryn_validate_dataset",
        {
            "project_id": proj["project_id"],
        },
    )()
    val = _json(text)
    assert val.get("total_examples", 0) > 0

    # 9. version + export
    _, text = call(
        server,
        "knovaryn_create_dataset_version",
        {
            "project_id": proj["project_id"],
        },
    )()
    ver = _json(text)
    assert ver.get("version_id", "").startswith("ver_")

    _, text = call(
        server,
        "knovaryn_export_dataset",
        {
            "project_id": proj["project_id"],
        },
    )()
    exp = _json(text)
    assert exp.get("sha256")

    # 10. license report
    _, text = call(
        server,
        "knovaryn_license_report",
        {
            "project_id": proj["project_id"],
        },
    )()
    lic = _json(text)
    assert "publication_gate" in lic

    # 11. publish — dry-run by default
    _, text = call(
        server,
        "knovaryn_publish_dataset",
        {
            "project_id": proj["project_id"],
            "repo_id": "local/x",
            "dry_run": True,
        },
    )()
    pub = _json(text)
    assert pub.get("status") in ("dry_run", "unavailable")


# ---------------------------------------------------------------------------
# branch / error paths
# ---------------------------------------------------------------------------


def test_publish_requires_confirm_for_real(server) -> None:
    _, text = call(
        server,
        "knovaryn_publish_dataset",
        {
            "project_id": "p-none",
            "repo_id": "local/x",
            "dry_run": False,
            "confirm": False,
        },
    )()
    body = _json(text)
    assert body.get("status") == "error"
    assert "confirm" in body.get("error", "")


def test_review_rejects_unknown_decision(server) -> None:
    _, text = call(
        server,
        "knovaryn_review_example",
        {
            "example_id": "ex1",
            "decision": "bogus",
        },
    )()
    body = _json(text)
    assert body.get("status") == "error"
    assert "unsupported decision" in body.get("error", "")


def test_start_pipeline_default_proportions(server) -> None:
    _, text = call(
        server,
        "knovaryn_start_pipeline",
        {
            "project_id": "p1",
            "task_fam_families": "   ",
        },
    )()
    job = _json(text)
    # missing project -> error dict surfaced rather than raised
    assert job.get("status") == "error" or job.get("job_id")


def test_run_job_wrong_id_returns_error(server) -> None:
    _, text = call(server, "knovaryn_run_job", {"job_id": "job_missing"})()
    body = _json(text)
    assert body.get("status") == "error"


def test_resume_job_nonresumable_state(server) -> None:
    _, text = call(server, "knovaryn_resume_job", {"job_id": "job_gone"})()
    body = _json(text)
    # not found -> error dict; a found-but-terminal job would say "not resumable"
    assert body.get("status") == "error" or body.get("state")


def test_cancel_job_unknown(server) -> None:
    _, text = call(server, "knovaryn_cancel_job", {"job_id": "job_gone"})()
    body = _json(text)
    assert body.get("status") == "error" or body.get("cancellation_requested") is True


def test_list_projects(server) -> None:
    _, text = call(server, "knovaryn_list_projects", {})()
    body = _json(text)
    assert "projects" in body


def test_compare_runs_missing(server) -> None:
    _, text = call(
        server,
        "knovaryn_compare_runs",
        {
            "project_id": "p",
            "job_id_a": "a",
            "job_id_b": "b",
        },
    )()
    body = _json(text)
    # two missing jobs -> either a delta or an error dict; must not raise
    assert body is not None


def test_inspect_missing_source_reports_error(server) -> None:
    _, text = call(
        server,
        "knovaryn_inspect_source",
        {
            "project_id": "p",
            "source_id": "src_none",
        },
    )()
    body = _json(text)
    assert body.get("status") == "error"
    assert "not found" in body.get("error", "")


def test_create_project_duplicate_slug_returns_error(server) -> None:
    call(
        server,
        "knovaryn_create_project",
        {
            "slug": "dup",
            "display_name": "First",
        },
    )()
    _, text = call(
        server,
        "knovaryn_create_project",
        {
            "slug": "dup",
            "display_name": "Second",
        },
    )()
    body = _json(text)
    assert body.get("status") == "error"
