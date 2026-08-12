"""MCP server (spec §17 / WP F2, F4) — offline integration tests for the tool surface.

Builds the real :func:`knovaryn.interfaces.mcp.server.build_server` with ``mcp``
installed, connects a client over an in-memory transport, and drives the full
``knovaryn_*`` tool set against a throwaway SQLite workspace with the fake
provider (no API keys, no network). In line with WP F2, every handler is a
*native async* function sharing a lifespan-managed :class:`Workspace`, so tests
await tool calls directly in the running loop — there is no ``asyncio.run()``
bridge and no background-loop monkeypatch.

The flagship assertion is provenance: every example returned by the preview
tool carries ``source_document_ids`` and ``source_span_ids`` (the enforced
provenance-minimum gate), verified through the agent-facing MCP surface.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from knovaryn.interfaces.mcp.server import SERVER_ID, build_server


@pytest.fixture
async def server(tmp_path: Path):
    """A built FastMCP server with a hermetic, throwaway SQLite workspace.

    ``build_server(database_url=...)`` hands the lifespan constructor an
    explicit database URL, so there is no config monkeypatch and no shared
    singleton to reset — the workspace is created and disposed by the server's
    own lifespan on connect/disconnect (WP F2).
    """
    db_url = f"sqlite+aiosqlite:///{tmp_path}/mcp.db"
    return build_server(database_url=db_url)


@asynccontextmanager
async def _session(server: Any) -> AsyncIterator[Any]:
    """A connected MCP ClientSession over the in-memory transport.

    Some ``mcp`` versions reject anonymous clients, so we provide an explicit
    ``client_info`` implementation handle.
    """
    from mcp.shared.memory import create_connected_server_and_client_session
    from mcp.types import Implementation

    client_info = Implementation(name="knovaryn-test", version="0.0.0")
    async with create_connected_server_and_client_session(
        server, client_info=client_info
    ) as session:
        yield session


def _block_text(block: Any) -> str | None:
    if isinstance(block, dict):
        return block.get("text")
    return getattr(block, "text", None)


async def acall(
    server: Any, tool: str, arguments: dict[str, Any] | None = None
) -> tuple[Any, str]:
    """Await ``tool`` with ``arguments`` through a fresh connected session."""
    async with _session(server) as session:
        result = await session.call_tool(tool, arguments or {})
    texts = []
    for block in getattr(result, "content", result or []):
        txt = _block_text(block)
        if txt is not None:
            texts.append(txt)
    return result, "\n".join(texts)


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


# ---------------------------------------------------------------------------
# health / doctor
# ---------------------------------------------------------------------------


async def test_health(server) -> None:
    _, text = await acall(server, "health")
    body = _json(text)
    assert body.get("status") == "ok"
    assert body.get("server_id") == SERVER_ID


async def test_doctor_lists_runtime_profiles(server) -> None:
    _, text = await acall(server, "knovaryn_doctor")
    body = _json(text)
    assert body.get("status") == "ok"
    assert "fake" in body.get("runtime_profiles", [])
    assert body.get("dependencies", {}).get("mcp") is True


# ---------------------------------------------------------------------------
# full lifecycle + provenance (flagship)
# ---------------------------------------------------------------------------


async def test_full_lifecycle_with_provenance(server) -> None:
    # 1. create project
    _, text = await acall(
        server,
        "knovaryn_create_project",
        {"slug": "mcp-widgets", "display_name": "MCP Widgets"},
    )
    proj = _json(text)
    assert proj.get("project_id", "").startswith("proj_")

    # 2. add source
    _, text = await acall(
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
    )
    src = _json(text)
    assert src.get("status") == "ok"
    assert src.get("source_id", "").startswith("src_")

    # 3. queue the job
    _, text = await acall(
        server,
        "knovaryn_start_pipeline",
        {"project_id": proj["project_id"], "task_fam_families": "factual_explanation:1.0"},
    )
    job_id = _json(text).get("job_id")
    assert job_id

    _, text = await acall(server, "knovaryn_get_job", {"job_id": job_id})
    gj = _json(text)
    assert "resources" in gj
    assert gj["resources"]["job"].endswith(f"/projects/{proj['project_id']}/jobs/{job_id}")

    # 4. run job offline
    _, text = await acall(server, "knovaryn_run_job", {"job_id": job_id})
    run = _json(text)
    assert run.get("state") == "succeeded", run

    # 4b. list jobs (WP F4)
    _, text = await acall(server, "knovaryn_list_jobs", {"project_id": proj["project_id"]})
    jobs = _json(text)
    assert any(j.get("id") == job_id for j in jobs.get("jobs", []))

    # 5. preview examples — PROVENANCE assertion
    _, text = await acall(
        server, "knovaryn_preview_examples", {"project_id": proj["project_id"], "limit": 100}
    )
    examples = _json(text).get("examples", [])
    assert examples, "pipeline must produce examples"
    for e in examples:
        assert e.get("source_document_ids"), f"example missing source_document_ids: {e}"
        assert e.get("source_span_ids"), f"example missing source_span_ids: {e}"
        assert e.get("_redacted") is True

    # 5b. lineage (WP F4)
    ex_id = examples[0].get("id")
    _, text = await acall(
        server,
        "knovaryn_lineage",
        {"project_id": proj["project_id"], "example_id": ex_id},
    )
    lin = _json(text)
    assert lin.get("example_id") == ex_id
    assert lin.get("source_document_ids")
    assert lin.get("lineage_uri", "").endswith(f"/examples/{ex_id}/lineage")

    # 6. inspect the added source
    _, text = await acall(
        server,
        "knovaryn_inspect_source",
        {"project_id": proj["project_id"], "source_id": src["source_id"]},
    )
    insp = _json(text)
    assert insp.get("source_id") == src["source_id"]
    assert insp.get("media_type") == "text/markdown"

    # 7. review an example (accept)
    _, text = await acall(
        server, "knovaryn_review_example", {"example_id": ex_id, "decision": "accept"}
    )
    assert _json(text).get("status") == "recorded"

    # 8. validate dataset
    _, text = await acall(server, "knovaryn_validate_dataset", {"project_id": proj["project_id"]})
    val = _json(text)
    assert val.get("total_examples", 0) > 0

    # 9. version + export
    _, text = await acall(
        server, "knovaryn_create_dataset_version", {"project_id": proj["project_id"]}
    )
    assert _json(text).get("version_id", "").startswith("ver_")

    _, text = await acall(server, "knovaryn_export_dataset", {"project_id": proj["project_id"]})
    assert _json(text).get("sha256")

    # 10. license report
    _, text = await acall(server, "knovaryn_license_report", {"project_id": proj["project_id"]})
    lic = _json(text)
    assert "publication_gate" in lic

    # 11. publish — dry-run by default
    _, text = await acall(
        server,
        "knovaryn_publish_dataset",
        {"project_id": proj["project_id"], "repo_id": "local/x", "dry_run": True},
    )
    pub = _json(text)
    assert pub.get("status") in ("dry_run", "unavailable")


# ---------------------------------------------------------------------------
# branch / error paths
# ---------------------------------------------------------------------------


async def test_publish_requires_confirm_for_real(server) -> None:
    _, text = await acall(
        server,
        "knovaryn_publish_dataset",
        {"project_id": "p-none", "repo_id": "local/x", "dry_run": False, "confirm": False},
    )
    body = _json(text)
    assert body.get("status") == "error"
    assert "confirm" in body.get("error", "")


async def test_review_rejects_unknown_decision(server) -> None:
    _, text = await acall(
        server, "knovaryn_review_example", {"example_id": "ex1", "decision": "bogus"}
    )
    body = _json(text)
    assert body.get("status") == "error"
    assert "unsupported decision" in body.get("error", "")


async def test_run_job_wrong_id_returns_error(server) -> None:
    _, text = await acall(server, "knovaryn_run_job", {"job_id": "job_missing"})
    assert _json(text).get("status") == "error"


async def test_cancel_job_unknown(server) -> None:
    _, text = await acall(server, "knovaryn_cancel_job", {"job_id": "job_gone"})
    body = _json(text)
    assert body.get("status") == "error" or body.get("cancellation_requested") is True


async def test_list_projects(server) -> None:
    _, text = await acall(server, "knovaryn_list_projects", {})
    assert "projects" in _json(text)


async def test_lineage_missing_example_reports_error(server) -> None:
    _, text = await acall(
        server, "knovaryn_lineage", {"project_id": "p", "example_id": "ex_none"}
    )
    body = _json(text)
    assert body.get("authorized") is False
    assert "not found" in body.get("error", "")


async def test_inspect_missing_source_reports_error(server) -> None:
    _, text = await acall(
        server, "knovaryn_inspect_source", {"project_id": "p", "source_id": "src_none"}
    )
    body = _json(text)
    assert body.get("status") == "error"
    assert "not found" in body.get("error", "")


async def test_create_project_duplicate_slug_returns_error(server) -> None:
    await acall(server, "knovaryn_create_project", {"slug": "dup", "display_name": "First"})
    _, text = await acall(
        server, "knovaryn_create_project", {"slug": "dup", "display_name": "Second"}
    )
    assert _json(text).get("status") == "error"
