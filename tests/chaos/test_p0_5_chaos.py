"""P0-5 chaos test — kill, lease-expire, reclaim, resume-no-repeat (spec §12).

Reproduces the production defect catch that WP E fixes: a worker killed mid-run
must not lose committed stage checkpoints, and a replacement worker reclaiming
the job must resume from the last durable checkpoint without repeating the
completed stages' paid provider calls.

Scenario (faithful to the P0-5 repro sequence):
  1. A multi-stage job is claimed by worker A and run through the JobEngine.
  2. Completed stages are durably committed to ``job_checkpoints``.
  3. Worker A "dies" during the final ``generate`` stage (simulated as a hard
     exception after the earlier stages checkpointed).
  4. The lease expires and no worker claims it — we model the reclaim by
     returning the job to ``queued`` (as ``claim_eligible`` would on a fresh
     claim after lease expiry).
  5. Worker B reclaims and re-runs the same stage list through the engine.
  6. The engine reads the durable completed stages and skips them.
  7. The remaining stage completes; the job reaches ``succeeded``.
  8. Proof: the provider-call ledger for the completed stages shows exactly one
     call each — the completed paid calls were NOT repeated on resume.
  9. Proof: durable checkpoints, events, status, and cost survived the crash.

The stage functions are lightweight fakes that record a provider-call entry to
a module-scoped ledger so the test can count calls across the two passes —
this exercises the *durability mechanism*, not generation correctness (that is
covered by the WP D generation tests).
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from knovaryn.application.workspace import Workspace
from knovaryn.domain.errors import KnovarynError
from knovaryn.domain.ids import IdGenerator
from knovaryn.domain.schemas import Job, JobState
from knovaryn.infrastructure.database.repositories import JobRepository
from knovaryn.pipeline.jobs.engine import JobEngine, StageContext
from knovaryn.pipeline.jobs.retry import RetryPolicy
from knovaryn.pipeline.jobs.state import StateMachine

# ---------------------------------------------------------------------------
# provider-call ledger shared across the two worker passes
# ---------------------------------------------------------------------------

_PROVIDER_CALLS: deque[tuple[str, int]] = deque()  # (stage, seq)


def _reset_calls() -> None:
    _PROVIDER_CALLS.clear()


def _count(stage: str) -> int:
    return sum(1 for s, _ in _PROVIDER_CALLS if s == stage)


# A crash marker that is NOT retryable and represents the worker "dying" — the
# engine swallows it and persists the job (failed), but the durable checkpoints
# already written before generate are the resume source of truth.
class WorkerDied(KnovarynError):
    code = "worker_died"

    def __init__(self) -> None:
        super().__init__("worker killed mid-generation")


_SAMPLE_SOURCE = "# Widget\n\nTurn widgets green. A widget has a knob."


@pytest.fixture
async def workspace(tmp_path: Path) -> Workspace:
    db = tmp_path / "knovaryn-chaos.db"
    ws = Workspace(database_url=f"sqlite+aiosqlite:///{db}", principal="test")
    await ws.open()
    yield ws
    await ws.close()


def _make_stages(crash_on_generate: bool) -> list[tuple[str, Any]]:
    """Build a 4-stage list; ``generate`` raises iff ``crash_on_generate``.

    Provider calls are counted in ``_PROVIDER_CALLS`` so the test can prove that
    the completed stages' paid calls are not repeated when the durable resume
    path skips them on the replacement worker's run.
    """

    async def _run_stage(ctx: StageContext, name: str, payload: dict) -> dict:
        _PROVIDER_CALLS.append((name, len(_PROVIDER_CALLS)))
        await ctx.checkpoint(name, key=f"{name}:result", value=payload)
        await ctx.event(f"{name} complete", event_type="stage_complete", stage=name)
        return payload

    async def parse(ctx: StageContext) -> dict:
        return await _run_stage(ctx, "parse", {"parsed": 1})

    async def chunk(ctx: StageContext) -> dict:
        return await _run_stage(ctx, "chunk", {"chunk": 1})

    async def split(ctx: StageContext) -> dict:
        return await _run_stage(ctx, "split", {"split": 1})

    async def generate(ctx: StageContext) -> dict:
        # this stage is the one that "dies" mid-run in worker pass A
        _PROVIDER_CALLS.append(("generate", len(_PROVIDER_CALLS)))
        await ctx.event("generate started", event_type="stage_start", stage="generate")
        if crash_on_generate:
            raise WorkerDied()
        await ctx.checkpoint("generate", key="generate:result", value={"examples": 3})
        await ctx.event("generate complete", event_type="stage_complete", stage="generate")
        return {"examples": 3}

    return [
        ("parse", parse),
        ("chunk", chunk),
        ("split", split),
        ("generate", generate),
    ]


async def _reclaim(job: Job, repo: JobRepository) -> None:
    """Model lease expiry + a replacement worker reclaiming the job."""
    # force the lease to have expired (heartbeats stopped after the kill) and
    # return the job to a claimable state
    job.lease_owner = None
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    job.state = JobState.queued
    job.finished_at = None
    await repo.save(job)


async def _queue_job(workspace: Workspace, slug: str) -> Job:
    proj = await workspace.create_project(slug=slug, display_name="Chaos Widgets")
    await workspace.add_source(
        project_id=proj.id,
        original_name="widget.md",
        media_type="text/markdown",
        content=_SAMPLE_SOURCE,
    )
    job = await workspace.start_pipeline(project_id=proj.id, task_family_proportions={})
    assert job.state == JobState.queued
    return job


async def test_p0_5_kill_lease_expire_reclaim_resume_no_repeat(
    workspace: Workspace,
) -> None:
    """End-to-end chaos recovery: killed worker, expired lease, no paid-call repeat."""
    _reset_calls()
    ids = IdGenerator()
    job = await _queue_job(workspace, "chaos")

    async with workspace._db.session() as session:
        repo = JobRepository(session, ids)

        # --- worker pass A: claim and run, dies inside `generate` ------------
        job_a = await repo.get(job.id)
        assert job_a is not None
        sm = StateMachine(job_a.state)
        if sm.can_transition(JobState.leased):
            sm.transition(JobState.leased)
            job_a.state = JobState.leased
            job_a.lease_owner = "worker-a"
            job_a.lease_expires_at = datetime.now(UTC) + timedelta(seconds=300)
        await repo.save(job_a)

        engine = JobEngine(
            ids=ids, repo=repo, retry_policy=RetryPolicy(max_attempts=0)
        )
        result = await engine.run(job_a, _make_stages(crash_on_generate=True))
        completed = await repo.completed_checkpoints(job_a.id)
        assert completed == ["parse", "chunk", "split"]
        assert result.state == JobState.failed
        assert result.error_code == "worker_died"

        # durable rows exist in job_checkpoints for the 3 completed stages
        from sqlalchemy import text

        rows = (
            await session.execute(
                text(
                    "SELECT stage_name, status FROM job_checkpoints "
                    "WHERE job_id=:j ORDER BY checkpoint_sequence"
                ).bindparams(j=job_a.id)
            )
        ).all()
        names = [r[0] for r in rows]
        # each completed stage is durably recorded (its own `:result` checkpoint
        # plus the engine's post-completion `:done` checkpoint)
        unique_ordered: list[str] = []
        for n in names:
            if n not in unique_ordered:
                unique_ordered.append(n)
        assert unique_ordered == ["parse", "chunk", "split"]
        assert all(r[1] == "completed" for r in rows)

        # ---- lease expiry + replacement worker reclaim (worker B) -----------
        await _reclaim(job_a, repo)
        claimed = await repo.claim_eligible(worker="worker-b", lease_seconds=300)
        assert claimed is not None and claimed.id == job_a.id

        # worker B re-runs the FULL stage list; engine resumes from durable
        # checkpoints (skips parse/chunk/split) and completes `generate`.
        engine_b = JobEngine(
            ids=ids, repo=repo, retry_policy=RetryPolicy(max_attempts=0)
        )
        result_b = await engine_b.run(claimed, _make_stages(crash_on_generate=False))
        assert result_b.state == JobState.succeeded

        # proof: completed provider calls were NOT repeated. parse/chunk/split
        # ran exactly once (pass A); worker B's resume did NOT re-invoke them.
        # generate ran once in pass A (died) and once in pass B (completed) —
        # that in-flight stage is legitimately re-run.
        assert _count("parse") == 1, "parse provider call was repeated on resume"
        assert _count("chunk") == 1, "chunk provider call was repeated on resume"
        assert _count("split") == 1, "split provider call was repeated on resume"
        assert _count("generate") == 2  # once (died) + once (completed)

        # proof: pass-A events survived the crash (present exactly once)
        events, _ = await repo.get_events(job_a.id, limit=1000)
        msgs = [e.message for e in events]
        for ev in ("parse complete", "chunk complete", "split complete"):
            assert msgs.count(ev) == 1, f"event {ev!r} lost or duplicated: {msgs}"

        # proof: cost / status / artifacts survived the crash
        assert result_b.actual_cost >= 0.0
        assert result_b.started_at is not None and result_b.finished_at is not None
        final_ck = await repo.completed_checkpoints(job_a.id)
        assert final_ck == ["parse", "chunk", "split", "generate"]


async def test_p0_5_resume_skips_completed_stages_even_on_clean_rerun(
    workspace: Workspace,
) -> None:
    """A full re-run after a crash must not recompute checkpoint-complete stages."""
    _reset_calls()
    ids = IdGenerator()
    job = await _queue_job(workspace, "resume")

    async with workspace._db.session() as session:
        repo = JobRepository(session, ids)
        await _reclaim(job, repo)
        claimed = await repo.claim_eligible(worker="worker-a", lease_seconds=300)
        assert claimed is not None

        # pass A: crash during generate (parse/chunk/split committed)
        engine = JobEngine(
            ids=ids, repo=repo, retry_policy=RetryPolicy(max_attempts=0)
        )
        res_a = await engine.run(claimed, _make_stages(crash_on_generate=True))
        assert res_a.state == JobState.failed
        assert _count("parse") == 1 and _count("chunk") == 1 and _count("split") == 1

        # pass B: reclaim + rerun; engine must skip the committed 3 stages
        await _reclaim(res_a, repo)
        claimed_b = await repo.claim_eligible(worker="worker-b", lease_seconds=300)
        assert claimed_b is not None
        res_b = await engine.run(claimed_b, _make_stages(crash_on_generate=False))
        assert res_b.state == JobState.succeeded
        # completed stages still count exactly once across both passes
        assert _count("parse") == 1 and _count("chunk") == 1 and _count("split") == 1
        assert _count("generate") == 2
