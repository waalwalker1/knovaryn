"""A6 export provenance gate tests (spec §15 / WP H4).

Proves the export path is fail-closed: a dataset whose lineage is unresolvable
or cross-project (rule 13/14) raises ``ExportError`` before anything is
serialized, and a healthy pipeline-produced dataset exports with a resolvable
artifact + digest. Contract rule 6 is honored (real identifier resolution, not
truthiness-only checks).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from knovaryn.application.workspace import Workspace
from knovaryn.domain.errors import ExportError
from knovaryn.domain.schemas import JobState

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def run(coro):
    return _LOOP.run_until_complete(coro)


CONTENT = """# Widgets
## Assembly
The widget is assembled from a base plate and a lid.
The lid must be torqued to 5 N·m.
## Inspection
Each unit is inspected for cracks before it ships.
"""


@pytest.fixture
def workspace(tmp_path: Path):
    db = tmp_path / "knovaryn.db"
    ws = Workspace(database_url=f"sqlite+aiosqlite:///{db}", principal="test")
    run(ws.open())
    yield ws
    run(ws.close())


def _project_with_examples(workspace: Workspace) -> str:
    proj = run(workspace.create_project(slug="gate", display_name="Gate"))
    run(
        workspace.add_source(
            project_id=proj.id, original_name="a.md", media_type="text/markdown", content=CONTENT
        )
    )
    job = run(
        workspace.start_pipeline(
            project_id=proj.id, task_family_proportions={"factual_explanation": 1.0}
        )
    )
    result = run(workspace.run_job(job.id))
    assert result["state"] == JobState.succeeded.value
    return proj.id


def test_export_passes_gate_and_returns_resolvable_digest(workspace: Workspace):
    """Healthy dataset: export succeeds with a resolvable artifact + digest
    (contract rule 13 — never a successful response without a verifiable hash)."""
    proj = _project_with_examples(workspace)  # returns the project_id string
    exported = run(workspace.export_dataset(project_id=proj))
    assert exported["bytes"] > 0
    assert exported["sha256"], "must return a verifiable digest (rule 13)"
    assert len(exported["sha256"]) == 64


def test_export_dataset_formatted_returns_export_artifact(workspace: Workspace, tmp_path):
    """H5: the formatted export returns a full ExportArtifact response with a
    resolvable artifact_id, digest, per-split counts and manifest artifact."""
    proj = _project_with_examples(workspace)  # returns project_id string

    art = run(
        workspace.export_dataset_formatted(
            project_id=proj, format="openai_chat", download_dir=str(tmp_path / "exports")
        )
    )
    # H5 returns an ExportArtifact schema object
    assert art.artifact_id.startswith("art_")
    assert art.download_path, "must reference a resolvable artifact path"
    assert art.media_type == "application/jsonl"
    assert art.format == "openai_chat"
    assert art.record_count > 0
    assert art.sha256, "H5 must return a verifiable digest (rule 13)"
    assert sum(art.per_split_counts.values()) == art.record_count
    assert art.manifest_artifact_id, "a content manifest artifact must be recorded"

    # the recorded sha256 actually matches the bytes on disk (not truthiness-only)
    raw = run(workspace._artifact_store().get(art.artifact_id))
    import hashlib

    assert hashlib.sha256(raw).hexdigest() == art.sha256


def test_export_fails_closed_on_unresolvable_lineage(workspace: Workspace):
    """A6: an example whose source_span cannot be resolved to a cited source
    document blocks the export with ExportError (rule 14 fail-closed)."""
    from knovaryn.application.workspace import _ExportResolver
    from knovaryn.domain.schemas import CanonicalMessage, Topology, TrainingExample
    from knovaryn.infrastructure.database.repositories import (
        CandidateRepository,
        ParsedRepository,
        SourceRepository,
        SpanRepository,
    )
    from knovaryn.pipeline.export.gate import verify_provenance_before_export

    ex = TrainingExample(
        id="ex_broken",
        project_id="proj_missing",
        topology=Topology.sft,
        system_messages=[],
        prompt_messages=[CanonicalMessage(role="user", content="q")],
        chosen_messages=[CanonicalMessage(role="assistant", content="a")],
        rejected_messages=[],
        source_span_ids=["sp_does_not_exist"],
        source_document_ids=["src_does_not_exist"],
        generation_candidate_ids=[],
        split="train",
        content_hash="",
    )

    async def _run():
        async with workspace._db.session() as session:
            resolver = _ExportResolver(
                sources=SourceRepository(session),
                spans=SpanRepository(session),
                parsed=ParsedRepository(session),
                candidates=CandidateRepository(session),
            )
            with pytest.raises(ExportError):
                await verify_provenance_before_export([ex], resolver)

    run(_run())
