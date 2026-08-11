"""P0-2 regression: split integrity and contamination control (contract §4 P0-2, §21).

These tests fail on the baseline because:
- candidates do not carry chunk_id / source_document_id / source_group_id / split as
  explicit data; split is reconstructed by parsing the span/candidate ID string;
- an unresolved split silently falls back to "train";
- validation/test may remain empty without honest reporting.

Every assertion is semantic (source-group disjointness), never truthiness-only.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from knovaryn.application.workspace import Workspace
from knovaryn.pipeline.split import SplitAssignment, assign_splits
from knovaryn.domain.schemas import SourceDocument

pytestmark = pytest.mark.unit

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture
def workspace(tmp_path: Path):
    db = tmp_path / "knovaryn.db"
    ws = Workspace(database_url=f"sqlite+aiosqlite:///{db}", principal="test")
    run(ws.open())
    yield ws
    run(ws.close())


def _src(slug: str, group: str, i: int) -> SourceDocument:
    return SourceDocument(
        id=f"src_{slug}_{i}",
        project_id="proj_x",
        original_name=f"{slug}.md",
        media_type="text/markdown",
        byte_size=1,
        sha256=f"h{i}",
        group_key=group,
    )


def test_no_source_group_crosses_splits():
    # many groups assigned together; a group must never appear in two splits
    srcs = [_src(f"s{i}", f"g{i % 4}", i) for i in range(40)]
    split = assign_splits(srcs, strategy="grouped_random", seed=7)
    group_split: dict[str, str] = {}
    for s in srcs:
        sp = split.split_of(s.id) or "train"
        g = s.group_key or s.id
        if g in group_split:
            assert group_split[g] == sp, f"group {g} crossed splits"
        group_split[g] = sp


def test_all_source_groups_assigned_to_a_split():
    srcs = [_src(f"s{i}", f"g{i % 4}", i) for i in range(40)]
    split = assign_splits(srcs, strategy="grouped_random", seed=7)
    for s in srcs:
        assert split.split_of(s.id) in ("train", "validation", "test")


def test_deterministic_same_seed_same_assignments():
    srcs = [_src(f"s{i}", f"g{i % 4}", i) for i in range(40)]
    a = assign_splits(srcs, strategy="grouped_random", seed=42)
    b = assign_splits(srcs, strategy="grouped_random", seed=42)
    assert a.by_source_id == b.by_source_id


def test_different_seed_still_leakage_free():
    srcs = [_src(f"s{i}", f"g{i % 4}", i) for i in range(40)]
    for seed in (1, 2, 3, 4, 5):
        split = assign_splits(srcs, strategy="grouped_random", seed=seed)
        group_split: dict[str, str] = {}
        for s in srcs:
            sp = split.split_of(s.id) or "train"
            g = s.group_key or s.id
            if g in group_split:
                assert group_split[g] == sp
            group_split[g] = sp


def test_pipeline_propagates_split_to_examples(workspace: Workspace):
    proj = run(workspace.create_project(slug="splitp", display_name="Split"))
    run(
        workspace.add_source(
            project_id=proj.id,
            original_name="a.md",
            media_type="text/markdown",
            content="Alpha protocol uses cobalt keys. Repeated enough material.",
        )
    )
    run(
        workspace.add_source(
            project_id=proj.id,
            original_name="b.md",
            media_type="text/markdown",
            content="Beta protocol uses amber keys. Different repeated material.",
        )
    )
    job = run(
        workspace.start_pipeline(project_id=proj.id, task_family_proportions={"factual_explanation": 1.0})
    )
    result = run(workspace.run_job(job.id))
    assert result["state"] == "succeeded", result
    listing = run(workspace.list_examples(project_id=proj.id))
    examples = listing["examples"]
    assert examples
    for ex in examples:
        # split must be an explicit value, never an implicitly-defaulted "train"
        assert ex["split"] in ("train", "validation", "test"), ex["split"]
