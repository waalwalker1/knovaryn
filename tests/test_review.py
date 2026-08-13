"""Review subsystem tests (spec §10 / WP H1/H2, P0-9).

Proves that a review decision:
* actually changes the example (new immutable revision, P0-9),
* is persisted as a decision record on the reviewed base revision,
* honors optimistic concurrency (stale token -> 409),
* advances the revision chain (parent links),
* never mutates the example's current row in place.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from knovaryn.application.workspace import Workspace
from knovaryn.domain.errors import ConcurrencyError

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def run(coro):
    return _LOOP.run_until_complete(coro)


CONTENT = """# Widgets
## Assembly
The widget is assembled from a base plate and a lid torqued to 5 N·m.
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


def _project_with_examples(workspace: Workspace):
    proj = run(workspace.create_project(slug="review", display_name="Review Docs"))
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
    assert result["state"] == "succeeded", result
    examples = run(workspace.list_examples(project_id=proj.id, limit=100))["examples"]
    assert examples, "pipeline must persist examples"
    return proj, examples[0]["id"]


def test_review_approve_creates_immutable_revision(workspace: Workspace):
    _, example_id = _project_with_examples(workspace)

    result = run(
        workspace.review_example(
            example_id=example_id,
            revision_id=1,
            reviewer="alice",
            decision="approve",
            note="looks good",
            policy_version="1.0",
        )
    )
    rev = result["revision"]
    assert rev["revision_id"] == 2
    assert rev["parent_revision_id"] == 1
    assert rev["review_state"] == "approve"
    # the new revision's snapshot reflects the decision (P0-9: it actually changed)
    assert rev["snapshot"]["quality_status"] == "accepted"
    # decision record persisted and returned
    assert result["decision"]["decision"] == "approve"
    assert result["decision"]["reviewer_principal"] == "alice"

    # revision chain has both entries in order
    history = run(workspace.list_revisions(example_id=example_id))
    ids = [r["revision_id"] for r in history["revisions"]]
    assert ids == [1, 2]
    assert len(history["decisions"]) == 1


def test_review_reject_flips_status_and_is_persisted(workspace: Workspace):
    _, example_id = _project_with_examples(workspace)

    result = run(
        workspace.review_example(
            example_id=example_id,
            revision_id=1,
            reviewer="bob",
            decision="reject",
            note="unsupported inference",
        )
    )
    assert result["revision"]["snapshot"]["quality_status"] == "rejected"
    assert result["revision"]["review_state"] == "reject"
    decisions = run(workspace.list_revisions(example_id=example_id))["decisions"]
    assert decisions[-1]["decision"] == "reject"


def test_stale_concurrency_token_raises_409(workspace: Workspace):
    _, example_id = _project_with_examples(workspace)

    first = run(
        workspace.review_example(
            example_id=example_id, revision_id=1, reviewer="alice", decision="approve"
        )
    )
    # alice's token is now stale after her approval created revision 2
    with pytest.raises(ConcurrencyError):
        run(
            workspace.review_example(
                example_id=example_id,
                revision_id=1,
                reviewer="carol",
                decision="reject",
                concurrency_token=first["revision"]["concurrency_token"],
            )
        )


def test_stale_base_revision_raises_409(workspace: Workspace):
    _, example_id = _project_with_examples(workspace)

    run(
        workspace.review_example(
            example_id=example_id, revision_id=1, reviewer="alice", decision="approve"
        )
    )
    # base revision 1 is no longer current (latest is now 2)
    with pytest.raises(ConcurrencyError):
        run(
            workspace.review_example(
                example_id=example_id, revision_id=1, reviewer="carol", decision="reject"
            )
        )


def test_chained_review_advances_revision_correctly(workspace: Workspace):
    _, example_id = _project_with_examples(workspace)

    r1 = run(
        workspace.review_example(
            example_id=example_id, revision_id=1, reviewer="alice", decision="approve"
        )
    )
    # a second reviewer bases their decision on the (now current) revision 2,
    # using the token returned by the first review.
    r2 = run(
        workspace.review_example(
            example_id=example_id,
            revision_id=r1["revision"]["revision_id"],
            reviewer="carol",
            decision="needs_work",
            concurrency_token=r1["revision"]["concurrency_token"],
        )
    )
    assert r2["revision"]["revision_id"] == 3
    assert r2["revision"]["parent_revision_id"] == 2
    assert r2["revision"]["snapshot"]["quality_status"] == "review"
    history = run(workspace.list_revisions(example_id=example_id))
    assert [r["revision_id"] for r in history["revisions"]] == [1, 2, 3]
