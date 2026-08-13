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
from knovaryn.domain.schemas import JobState, SourceKind

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


def test_add_source_binary_routes_artifact_first(workspace: Workspace, tmp_path: Path):
    """WP G: a binary added via add_source is artifact-first with a real SHA-256
    and is parsed (or quarantined) from its immutable original bytes."""
    import hashlib

    proj = run(workspace.create_project(slug="binproj", display_name="Binary"))
    raw = bytes([0x25, 0x50, 0x44, 0x46, 0x00, 0xFF, 0x00, 0x01])  # pdf-ish binary

    src = run(
        workspace.add_source(
            project_id=proj.id,
            original_name="blob.pdf",
            raw=raw,
            source_kind=SourceKind.upload,
        )
    )
    assert src.sha256 == hashlib.sha256(raw).hexdigest()  # real content hash
    assert src.artifact_id_original  # immutable original artifact persisted
    assert src.byte_size == len(raw)
    assert "content" not in (src.metadata or {})  # binary bytes NOT in metadata

    # pipeline parses from the artifact store, quarantining the unparseable binary
    job = run(workspace.start_pipeline(project_id=proj.id))
    result = run(workspace.run_job(job.id))
    assert result["state"] == JobState.succeeded.value


def test_version_snapshot_unchanged_by_review(workspace: Workspace):
    """WP H3: a version captures an immutable membership snapshot + parent chain.

    Reviewing (rejecting) an example afterwards must NOT change what an already-
    created version contains; only a NEW version reflects the decision.
    """
    proj = run(workspace.create_project(slug="verimm", display_name="Version Immutability"))
    run(
        workspace.add_source(
            project_id=proj.id,
            original_name="assembly.md",
            media_type="text/markdown",
            content=CONTENT,
        )
    )
    job = run(
        workspace.start_pipeline(
            project_id=proj.id, task_family_proportions={"factual_explanation": 1.0}
        )
    )
    result = run(workspace.run_job(job.id))
    assert result["state"] == JobState.succeeded.value

    v1 = run(workspace.create_version(project_id=proj.id, semantic_version="0.1.0"))
    assert v1.member_example_ids, "version must snapshot its member examples"
    member_ids = list(v1.member_example_ids)
    content_hash = v1.content_hash

    # reject one example after the version was created (P0-9 path)
    target = member_ids[0]
    reviewed = run(
        workspace.review_example(
            example_id=target, revision_id=1, reviewer="alice", decision="reject"
        )
    )
    assert reviewed["revision"]["snapshot"]["quality_status"] == "rejected"

    # v1 is unchanged: same membership, same content hash (version is immutable)
    v1_reloaded = run(workspace.get_version(version_id=v1.id))
    assert v1_reloaded.member_example_ids == member_ids
    assert v1_reloaded.content_hash == content_hash
    total = v1_reloaded.train_count + v1_reloaded.validation_count + v1_reloaded.test_count
    assert total == len(member_ids)

    # a second version chains to v1 and excludes the rejected example
    v2 = run(workspace.create_version(project_id=proj.id, semantic_version="0.1.1"))
    assert v2.parent_version_id == v1.id
    assert target not in v2.member_example_ids
    assert len(v2.member_example_ids) == len(member_ids) - 1


def test_publication_dry_run_emits_full_h6_plan(workspace: Workspace, monkeypatch):
    """H6: a publication dry-run returns a complete, side-effect-free plan with a
    verifiable detached checksum + artifact digests (no external side effects)."""
    import knovaryn.infrastructure.publish.hf as hf

    monkeypatch.setattr(hf, "hub_available", lambda: True)
    proj = run(workspace.create_project(slug="h6plan", display_name="H6 Plan"))
    run(
        workspace.add_source(
            project_id=proj.id,
            original_name="mit.md",
            media_type="text/markdown",
            content=CONTENT,
            declared_license="MIT",  # approved redistribution -> gate passes
        )
    )
    job = run(
        workspace.start_pipeline(
            project_id=proj.id, task_family_proportions={"factual_explanation": 1.0}
        )
    )
    result = run(workspace.run_job(job.id))
    assert result["state"] == JobState.succeeded.value

    plan = run(workspace.publish_dataset(project_id=proj.id, repo_id="local/h6", dry_run=True))
    assert plan["status"] == "dry_run", plan
    assert plan["destination"] == "local/h6"
    # H6 required plan fields
    assert plan["immutability_ok"] is True
    assert plan["provenance_verified"] is True
    assert plan["quality_gate"]["allowed"] is True
    assert plan["license_gate"]["allowed"] is True
    assert plan["human_review_ok"] is True
    assert plan["critical_warnings_resolved"] is True
    # I2: a real detached checksum (64 hex chars), not truthiness-only (rule 6/13)
    detached = plan["detached_checksum_sha256"]
    assert len(detached) == 64
    assert all(c in "0123456789abcdef" for c in detached)
    # the plan's artifact list maps logical paths to sha256 digests
    artifacts = plan["plan_artifacts"]
    assert any(a["logical_path"] == "release.zip.sha256" for a in artifacts)
    assert any(a["logical_path"] == "data/train.jsonl" for a in artifacts)
    for a in artifacts:
        assert len(a["sha256"]) == 64


def test_publication_dry_run_works_when_hub_unavailable(workspace: Workspace):
    """When huggingface-hub is not installed, dry-run reports 'unavailable' with
    the publication gate — never a fabricated success (rule 13)."""
    import knovaryn.infrastructure.publish.hf as hf

    proj = run(workspace.create_project(slug="h6unav", display_name="H6 Unav"))
    run(
        workspace.add_source(
            project_id=proj.id,
            original_name="mit.md",
            media_type="text/markdown",
            content=CONTENT,
            declared_license="MIT",
        )
    )
    job = run(workspace.start_pipeline(project_id=proj.id))
    run(workspace.run_job(job.id))
    # force hub unavailable even if installed (fail-closed for live publish)
    original = hf.hub_available
    hf.hub_available = lambda: False
    try:
        plan = run(workspace.publish_dataset(project_id=proj.id, repo_id="local/x"))
        assert plan["status"] == "unavailable"
        assert "publication_gate" in plan
    finally:
        hf.hub_available = original
