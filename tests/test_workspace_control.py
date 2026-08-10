"""End-to-end workspace control-plane tests (spec §17–§19).

Exercises the full offline lifecycle against a real SQLite store: create
project → add source → queue durable pipeline job → run → validate → version →
export → publish (dry-run). Runs deterministically with the fake provider.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from knovaryn.application.workspace import Workspace
from knovaryn.domain.schemas import JobState

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def run(coro):
    return _LOOP.run_until_complete(coro)


CONTENT = """# Widgets
## Assembly
The widget is assembled from a base plate and a lid.
The lid must be torqued to 5 N·m. Assembly takes about three minutes per unit.
## Inspection
Each unit is inspected for cracks before it ships.
Units with visible defects are quarantined and reworked.
"""


@pytest.fixture
def workspace(tmp_path: Path):
    db = tmp_path / "knovaryn.db"
    ws = Workspace(database_url=f"sqlite+aiosqlite:///{db}", principal="test")
    run(ws.open())
    yield ws
    run(ws.close())


def test_full_control_plane_lifecycle(workspace: Workspace):
    # 1. create project
    proj = run(workspace.create_project(slug="widgets", display_name="Widget Docs"))
    assert proj.id.startswith("proj_")
    assert proj.owner_principal == "test"

    # 2. add source
    src = run(
        workspace.add_source(
            project_id=proj.id,
            original_name="assembly.md",
            media_type="text/markdown",
            content=CONTENT,
        )
    )
    assert src.id.startswith("src_")
    assert src.sha256

    # 3. queue durable pipeline job
    job = run(
        workspace.start_pipeline(
            project_id=proj.id,
            task_family_proportions={"factual_explanation": 1.0},
        )
    )
    assert job.state == JobState.queued
    assert job.job_type == "pipeline"

    # 4. run job offline (single in-process worker)
    result = run(workspace.run_job(job.id))
    assert result["state"] == "succeeded", result
    assert result["error_code"] is None

    # 5. inspect job summary with events
    summary = run(workspace.get_job(job.id))
    assert summary.job.state == JobState.succeeded
    assert any(e.get("event_type") for e in summary.events)

    # 6. persisted examples were created
    examples = run(workspace.list_examples(project_id=proj.id, limit=100))
    assert len(examples["examples"]) > 0, "pipeline must persist accepted examples"

    # 7. validate
    report = run(workspace.validate_dataset(project_id=proj.id))
    assert report.get("total_examples", 0) > 0
    assert report["status_counts"].get("accepted", 0) > 0

    # 8. version
    version = run(workspace.create_version(project_id=proj.id, semantic_version="0.1.0"))
    assert version.id.startswith("ver_")
    assert version.train_count >= 0

    # 9. export
    exported = run(workspace.export_dataset(project_id=proj.id))
    assert exported["bytes"] > 0
    assert exported["lines"] >= 0
    assert exported["sha256"]

    # 10. publish (dry-run; no network, no auth required)
    pub = run(workspace.publish_dataset(project_id=proj.id, repo_id="local/widgets", dry_run=True))
    assert pub["status"] in ("dry_run", "unavailable")


def test_project_slug_uniqueness(workspace: Workspace):
    run(workspace.create_project(slug="dup", display_name="First"))
    from knovaryn.domain.errors import AlreadyExistsError

    with pytest.raises(AlreadyExistsError):
        run(workspace.create_project(slug="dup", display_name="Second"))


def test_idempotent_pipeline_start(workspace: Workspace):
    proj = run(workspace.create_project(slug="idem", display_name="Idem"))
    run(
        workspace.add_source(
            project_id=proj.id, original_name="a.md", media_type="text/markdown", content=CONTENT
        )
    )
    j1 = run(workspace.start_pipeline(project_id=proj.id, idempotency_key="key-1"))
    j2 = run(workspace.start_pipeline(project_id=proj.id, idempotency_key="key-1"))
    assert j1.id == j2.id


def test_license_report_and_publication_gate(workspace: Workspace):
    proj = run(workspace.create_project(slug="lic", display_name="Lic"))
    run(
        workspace.add_source(
            project_id=proj.id,
            original_name="mit.md",
            media_type="text/markdown",
            content=CONTENT,
            declared_license="MIT",
        )
    )
    run(
        workspace.add_source(
            project_id=proj.id,
            original_name="none.md",
            media_type="text/markdown",
            content=CONTENT,
            declared_license=None,
        )
    )

    report = run(workspace.license_report(project_id=proj.id))
    assert report["license"]["allowed"] == 1
    assert report["license"]["review"] == 1
    # unknown license defaults to review — never auto-allowed for public release
    assert report["publication_gate"]["allowed"] is False
    assert report["publication_gate"]["unresolved"]

    # publish is blocked pre-HF by the gate (dry run reports the gate)
    pub = run(workspace.publish_dataset(project_id=proj.id, repo_id="local/lic", dry_run=False))
    if pub["status"] != "unavailable":
        assert pub["status"] == "blocked"
        assert pub["publication_gate"]["allowed"] is False


def test_publish_blocked_on_unapproved_source(workspace: Workspace, monkeypatch):
    import knovaryn.infrastructure.publish.hf as hf

    monkeypatch.setattr(hf, "hub_available", lambda: True)
    proj = run(workspace.create_project(slug="pub", display_name="Pub"))
    run(
        workspace.add_source(
            project_id=proj.id,
            original_name="nd.md",
            media_type="text/markdown",
            content=CONTENT,
            declared_license="cc-by-nd",
        )
    )

    pub = run(workspace.publish_dataset(project_id=proj.id, repo_id="local/pub", dry_run=False))
    assert pub["status"] == "blocked"
    assert "blocked" in pub["reason"]
