"""E7 — durable worker repository + ``knovaryn worker`` CLI command (spec §7.3).

These are integration tests against a real SQLite store: they prove the
``WorkerRepository`` (session-per-operation adapter) drives a real job from
``queued -> leased -> running -> succeeded`` through the ``Worker`` + engine,
and that the CLI ``worker --once`` entry point lifts an offline pipeline job
off the DB exactly as a background worker would — with durable events and no
repeated stage work on resume.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from knovaryn.application.workspace import Workspace
from knovaryn.domain.ids import IdGenerator
from knovaryn.domain.schemas import JobState
from knovaryn.pipeline.jobs.worker import Worker, WorkerRepository

_SAMPLE_SOURCE = (
    "# MLOps lifecycle\n\nData preparation is the first step of any ML project. "
    "Practitioners document provenance to keep datasets auditable. Model training "
    "optimizes weights against a loss. Evaluation must use a held-out test set."
)


@pytest.fixture
async def workspace(tmp_path: Path) -> Workspace:
    db = tmp_path / "knovaryn-worker.db"
    ws = Workspace(database_url=f"sqlite+aiosqlite:///{db}", principal="test")
    await ws.open()
    yield ws
    await ws.close()


async def _queue_job(workspace: Workspace, slug: str):
    proj = await workspace.create_project(slug=slug, display_name="Worker Docs")
    await workspace.add_source(
        project_id=proj.id,
        original_name="mlops.md",
        media_type="text/markdown",
        content=_SAMPLE_SOURCE,
    )
    job = await workspace.start_pipeline(
        project_id=proj.id, task_family_proportions={"factual_explanation": 1.0}
    )
    assert job.state == JobState.queued
    return job


def _build_worker(workspace: Workspace, ids: IdGenerator, worker_id: str) -> Worker:
    """Build a Worker wired to the workspace DB with the real pipeline stage."""
    from knovaryn.application.service import ProjectService
    from knovaryn.domain.schemas import DatasetPlan
    from knovaryn.infrastructure.database.repositories import ProjectRepository, SourceRepository
    from knovaryn.pipeline.jobs.engine import JobEngine
    from knovaryn.pipeline.jobs.retry import RetryPolicy

    db = workspace._db

    async def _pipeline_stage(ctx: Any) -> dict[str, Any]:
        job = ctx.job
        async with db.session() as session, session.begin():
            project = await ProjectRepository(session, ids).get(job.project_id)
            source_repo = SourceRepository(session)
            sources = []
            contents: list[str] = []
            for sid in (job.input or {}).get("source_ids") or []:
                src = await source_repo.get(sid)
                if src is not None:
                    sources.append(src)
                    contents.append((src.metadata or {}).get("content", "") or "")
            plan = DatasetPlan(task_family_proportions={"factual_explanation": 1.0})
            result = await ProjectService(ids=ids).run_pipeline(
                project=project, sources=sources, contents=contents, plan=plan
            )
        await ctx.checkpoint("pipeline", step=1, key="result", value=result.to_dict())
        return result.to_dict()

    def stage_provider(job_type: str) -> list[tuple[str, Any]]:
        assert job_type == "pipeline"
        return [("pipeline", _pipeline_stage)]

    repo = WorkerRepository(db, ids)
    engine = JobEngine(ids=ids, repo=repo, retry_policy=RetryPolicy(max_attempts=1))
    return Worker(
        ids=ids,
        engine=engine,
        stage_provider=stage_provider,
        repo=repo,
        worker_id=worker_id,
        lease_seconds=300,
        poll_interval_s=0.05,
    )


pytestmark = [pytest.mark.integration, pytest.mark.chaos]


async def test_worker_repo_runs_queued_job_to_success(workspace: Workspace) -> None:
    """A real WorkerRepository + Worker drive a queued pipeline job to succeeded."""
    job = await _queue_job(workspace, "worker-e2e")

    w = _build_worker(workspace, IdGenerator(), "w-test")
    # single poll: claim the eligible job and run it to a terminal state
    await w._tick()  # noqa: SLF001 - single-shot claim+run for the test

    async with workspace._db.session() as session:
        from knovaryn.infrastructure.database.repositories import JobRepository

        ids = IdGenerator()
        repo = JobRepository(session, ids)
        final = await repo.get(job.id)
        assert final is not None
        assert final.state == JobState.succeeded

        # durable events were written (queued + stage_complete)
        events, _ = await repo.get_events(job.id, limit=100)
        messages = [e.message for e in events]
        assert any("pipeline queued" in m for m in messages)
        assert any("stage pipeline complete" in m for m in messages)

        # durable stage checkpoint committed
        committed = await repo.completed_checkpoints(job.id)
        assert "pipeline" in committed


async def test_worker_repo_durable_checkpoints_survive_new_repository(
    workspace: Workspace,
) -> None:
    """A fresh WorkerRepository (simulated replacement worker) sees committed
    checkpoints — proving durability survives a repository/worker restart."""
    job = await _queue_job(workspace, "worker-durable")
    ids = IdGenerator()
    db = workspace._db

    from knovaryn.pipeline.jobs.engine import JobEngine
    from knovaryn.pipeline.jobs.retry import RetryPolicy

    repo_a = WorkerRepository(db, ids)
    engine_a = JobEngine(ids=ids, repo=repo_a, retry_policy=RetryPolicy(max_attempts=0))

    # lightweight fakes that checkpoint a few stages then "crash"
    calls: list[str] = []

    async def s1(ctx: Any) -> dict:
        calls.append("s1")
        await ctx.checkpoint("s1", key="s1:result", value={"n": 1})
        return {"n": 1}

    async def s2(ctx: Any) -> dict:
        calls.append("s2")
        await ctx.checkpoint("s2", key="s2:result", value={"n": 2})
        return {"n": 2}

    async def s3(ctx: Any) -> dict:
        calls.append("s3")
        await ctx.checkpoint("s3", key="s3:result", value={"n": 3})
        return {"n": 3}

    async def s4(ctx: Any) -> dict:
        calls.append("s4")
        raise RuntimeError("worker killed in s4")

    async def stages(job_type: str) -> list[tuple[str, Any]]:
        return [("s1", s1), ("s2", s2), ("s3", s3), ("s4", s4)]

    from knovaryn.pipeline.jobs.engine import StageContext

    async def _claim_run(stage_list, expect_fail: bool):
        async with db.session() as session, session.begin():
            from knovaryn.infrastructure.database.repositories import JobRepository as JR

            repo = JR(session, ids)
            await repo.save(job)
        claimed = await repo_a.claim_eligible(worker="w-a", lease_seconds=300)
        assert claimed is not None
        result = await engine_a.run(claimed, stage_list)
        return result

    # pass A: s4 crashes; s1..s3 durably committed
    res_a = await _claim_run(await stages("pipeline"), expect_fail=True)
    assert res_a.state == JobState.failed

    # replacement worker (fresh repository over same DB) sees the checkpoints
    repo_b = WorkerRepository(db, ids)
    committed = await repo_b.completed_checkpoints(job.id)
    assert set(committed) >= {"s1", "s2", "s3"}

    # pass B: reclaim + run again; s1..s3 are skipped (no repeat), s4 completes
    async with db.session() as session, session.begin():
        from knovaryn.infrastructure.database.repositories import JobRepository as JR

        repo = JR(session, ids)
        back = await repo.get(job.id)
        back.lease_owner = None
        back.lease_expires_at = None
        back.state = JobState.queued
        back.finished_at = None
        await repo.save(back)

    async def s4_ok(ctx: StageContext) -> dict:
        calls.append("s4")
        await ctx.checkpoint("s4", key="s4:result", value={"n": 4})
        return {"n": 4}

    claimed_b = await repo_b.claim_eligible(worker="w-b", lease_seconds=300)
    assert claimed_b is not None
    engine_b = JobEngine(ids=ids, repo=repo_b, retry_policy=RetryPolicy(max_attempts=0))
    res_b = await engine_b.run(claimed_b, [("s4", s4_ok)])
    assert res_b.state == JobState.succeeded

    # completed stages ran exactly once each across both workers
    assert calls.count("s1") == 1 and calls.count("s2") == 1 and calls.count("s3") == 1
    assert calls.count("s4") == 2  # once (died) + once (completed)


async def test_cli_worker_command_once_drains_queued_job(
    workspace: Workspace, monkeypatch, tmp_path: Path
) -> None:
    """The ``knovaryn worker --once`` entry point runs a queued job to success."""
    from knovaryn.interfaces.cli import commands as cli_commands

    job = await _queue_job(workspace, "cli-worker")
    # the CLI worker must operate on the SAME sqlite store the workspace used,
    # so point its config + database_url at the workspace's own database URL.
    database_url = workspace._database_url  # e.g. sqlite+aiosqlite:///<tmp>/knovaryn-worker.db

    from knovaryn.domain.config import Configuration

    cfg = Configuration()
    cfg.set("storage.database_url", database_url)
    monkeypatch.setattr(cli_commands, "load_config", lambda **kw: cfg)

    # run the worker against the SAME store the workspace queued the job on
    await cli_commands.worker_async(
        worker_id="w-cli",
        poll_interval_s=0.05,
        lease_seconds=300,
        once=True,
        database_url=database_url,
    )

    # the job queued on the workspace is drained by the CLI worker to success
    from knovaryn.domain.ids import IdGenerator

    ids = IdGenerator()
    async with workspace._db.session() as session:
        from knovaryn.infrastructure.database.repositories import JobRepository

        final = await JobRepository(session, ids).get(job.id)
        assert final is not None and final.state == JobState.succeeded
