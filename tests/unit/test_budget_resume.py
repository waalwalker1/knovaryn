"""WP D7 regression tests: budget enforcement and resumable paused jobs.

The baseline enforced budgets only before a call and had no per-model / per-
stage sub-budgets, no post-usage reconciliation, and no resume API for a
budget-exhausted paused job. These tests lock in the D7 contract.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from knovaryn.application.workspace import Workspace
from knovaryn.domain.errors import BudgetExceededError, JobStateError
from knovaryn.domain.schemas import JobState
from knovaryn.pipeline.jobs.budget import BudgetState

pytestmark = pytest.mark.unit

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def run(coro):
    return _LOOP.run_until_complete(coro)


# ---------------------------------------------------------------------------
# BudgetState: hard limits before calls
# ---------------------------------------------------------------------------


def test_pre_call_cost_check_raises_when_at_limit() -> None:
    b = BudgetState(maximum_cost_usd=1.0)
    b.account_call(cost_usd=1.0)
    with pytest.raises(BudgetExceededError):
        b.check()


def test_pre_call_call_count_check_raises() -> None:
    b = BudgetState(maximum_calls=2, maximum_cost_usd=100.0)
    b.account_call(cost_usd=0.1, count=2)
    with pytest.raises(BudgetExceededError):
        b.check()


# ---------------------------------------------------------------------------
# BudgetState: post-usage reconciliation (D7)
# ---------------------------------------------------------------------------


def test_reconcile_raises_on_crossing_global_cost() -> None:
    b = BudgetState(maximum_cost_usd=1.0)
    b.account_call(cost_usd=0.6)
    # still under: reconcile passes
    b.reconcile()
    b.account_call(cost_usd=0.5)  # now at 1.1 >= 1.0
    with pytest.raises(BudgetExceededError):
        b.reconcile()


def test_per_model_sub_budget_reconcile() -> None:
    b = BudgetState(
        maximum_cost_usd=100.0,
        per_model_max_cost_usd={"deepseek-v4-flash": 1.0},
    )
    b.account_call(cost_usd=0.6, model="deepseek-v4-flash")
    b.reconcile(model="deepseek-v4-flash")
    b.account_call(cost_usd=0.5, model="deepseek-v4-flash")  # crosses per-model cap
    with pytest.raises(BudgetExceededError):
        b.reconcile(model="deepseek-v4-flash")


def test_per_stage_sub_budget_account_and_check() -> None:
    b = BudgetState(
        maximum_cost_usd=100.0,
        per_stage_max_cost_usd={"generate": 0.5},
    )
    b.account_call(cost_usd=0.5, stage="generate")
    with pytest.raises(BudgetExceededError):
        b.check(stage="generate")


def test_other_model_not_affected_by_per_model_cap() -> None:
    b = BudgetState(
        maximum_cost_usd=100.0,
        per_model_max_cost_usd={"deepseek-v4-flash": 1.0},
    )
    b.account_call(cost_usd=5.0, model="gpt-4o")  # no cap for gpt-4o
    b.reconcile(model="gpt-4o")  # must not raise on a model with no cap


# ---------------------------------------------------------------------------
# Workspace: resume a paused budget-exhausted job (D7)
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path):
    db = tmp_path / "knovaryn.db"
    ws = Workspace(database_url=f"sqlite+aiosqlite:///{db}", principal="test")
    run(ws.open())
    yield ws
    run(ws.close())


def _make_job(workspace: Workspace) -> Any:
    """Create a project with a source and a queued pipeline job."""
    proj = run(workspace.create_project(slug="budg", display_name="Budg"))
    run(workspace.add_source(
        project_id=proj.id,
        original_name="a.md",
        media_type="text/markdown",
        content="Alpha protocol uses cobalt keys. Repeated enough material to split.",
    ))
    job = run(workspace.start_pipeline(
        project_id=proj.id,
        task_family_proportions={"factual_explanation": 1.0},
    ))
    return job


def test_resume_transitions_paused_job_to_queued(workspace: Workspace) -> None:
    job = _make_job(workspace)

    # simulate a budget-exhausted pause at the persistence layer
    async def _pause() -> None:
        from knovaryn.infrastructure.database.repositories import JobRepository

        async with workspace._db.session() as session, session.begin():
            repo = JobRepository(session, workspace._ids)
            j = await repo.get(job.id)
            j.state = JobState.paused
            await repo.save(j)

    run(_pause())

    resumed = run(workspace.resume_job(job.id))
    assert resumed.state == JobState.queued


def test_resume_rejects_already_succeeded_job(workspace: Workspace) -> None:
    job = _make_job(workspace)

    async def _succeed() -> None:
        from knovaryn.infrastructure.database.repositories import JobRepository

        async with workspace._db.session() as session, session.begin():
            repo = JobRepository(session, workspace._ids)
            j = await repo.get(job.id)
            j.state = JobState.succeeded
            await repo.save(j)

    run(_succeed())

    with pytest.raises(JobStateError):
        run(workspace.resume_job(job.id))


def test_resume_unknown_job_raises(workspace: Workspace) -> None:
    from knovaryn.domain.errors import NotFoundError

    with pytest.raises(NotFoundError):
        run(workspace.resume_job("no_such_job"))
