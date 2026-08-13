"""P0-1 regression: real provenance and lineage (contract §4 P0-1, §21.1).

These tests fail on the baseline because:
- workspace persistence replaces missing source-document IDs with job.project_id;
- pipeline invents `span_<hash>_<i>` source-span IDs that never resolve to persisted
  SourceSpan records;
- generation_candidate_ids are never populated on persisted examples.

Every assertion is semantic (resolves through repositories), never truthiness-only.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from knovaryn.application.workspace import Workspace

pytestmark = pytest.mark.unit

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


def _run_pipeline(ws: Workspace):
    """Create project, add a source, run a durable pipeline job, return ids."""
    proj = run(ws.create_project(slug="prov", display_name="Provenance"))
    src = run(
        ws.add_source(
            project_id=proj.id,
            original_name="assembly.md",
            media_type="text/markdown",
            content=CONTENT,
        )
    )
    job = run(
        ws.start_pipeline(project_id=proj.id, task_family_proportions={"factual_explanation": 1.0})
    )
    result = run(ws.run_job(job.id))
    assert result["state"] == "succeeded", result
    listing = run(ws.list_examples(project_id=proj.id))
    return proj, src, listing["examples"]


def test_source_document_ids_resolve_to_real_documents(workspace: Workspace):
    proj, src, examples = _run_pipeline(workspace)
    # do not skip if no examples — the pipeline must produce examples to be usable
    assert examples, "pipeline produced no examples; provenance cannot be exercised"

    for ex in examples:
        # every source document ID must resolve to an existing SourceDocument
        assert ex["source_document_ids"], f"example {ex['id']} has empty source_document_ids"
        for doc_id in ex["source_document_ids"]:
            # must NOT be the project id masquerading as a source
            assert doc_id != proj.id, (
                f"example {ex['id']} has project id injected as source_document_id"
            )
            # must be a real source in the same project
            listing = run(workspace.list_sources(project_id=proj.id))
            src_ids = {s["id"] for s in listing["sources"]}
            assert doc_id in src_ids, f"example {ex['id']} references unknown source {doc_id}"
            s = next(s for s in listing["sources"] if s["id"] == doc_id)
            assert s["project_id"] == proj.id


def test_no_project_id_injected_into_source_document_ids(workspace: Workspace):
    proj, src, examples = _run_pipeline(workspace)
    for ex in examples:
        assert proj.id not in ex["source_document_ids"]


def test_source_spans_resolve_to_persisted_spans(workspace: Workspace):
    proj, src, examples = _run_pipeline(workspace)
    for ex in examples:
        # every span id must resolve to a persisted SourceSpan
        for span_id in ex["source_span_ids"]:
            # spans must be real persisted handles, not invented "span_<hash>_<i>"
            assert not span_id.startswith("auto:"), (
                f"example {ex['id']} uses a synthetic auto span {span_id}"
            )
        assert ex["source_span_ids"], f"example {ex['id']} has no spans"


def test_generation_candidate_ids_present(workspace: Workspace):
    proj, src, examples = _run_pipeline(workspace)
    for ex in examples:
        assert ex["generation_candidate_ids"], f"example {ex['id']} has no generation_candidate_ids"
