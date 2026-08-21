"""Regression tests: lease heartbeat renewed concurrently during long stages.

A worker whose single stage runs longer than its lease must keep renewing the
lease while the stage executes. Otherwise the lease expires mid-stage and (with
expired-lease reclaim in place) a second worker steals the job → the same paid
pipeline runs twice concurrently.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from knovaryn.application.workspace import Workspace
from knovaryn.domain.ids import IdGenerator
from knovaryn.domain.schemas import JobState
from knovaryn.infrastructure.database.repositories import JobRepository
from knovaryn.pipeline.jobs.engine import JobEngine
from knovaryn.pipeline.jobs.retry import RetryPolicy
from knovaryn.pipeline.jobs.worker import Worker, WorkerRepository

_SAMPLE = "# Doc\n\nHeartbeat test content."


def _aware(dt: datetime) -> datetime:
    """SQLite returns naive datetimes; normalize for comparison."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@pytest.fixture
async def workspace(tmp_path: Path) -> Workspace:
    db = tmp_path / "knovaryn-heartbeat.db"
    ws = Workspace(database_url=f"sqlite+aiosqlite:///{db}", principal="test")
    await ws.open()
    yield ws
    await ws.close()


async def _queued_job(ws: Workspace, slug: str) -> Any:
    proj = await ws.create_project(slug=slug, display_name="Heartbeat")
    await ws.add_source(
        project_id=proj.id,
        original_name="doc.md",
        media_type="text/markdown",
        content=_SAMPLE,
    )
    return await ws.start_pipeline(project_id=proj.id, task_family_proportions={})


class TestHeartbeatDuringLongStage:
    """Heartbeat must be renewed concurrently during long stages."""

    async def test_lease_survives_stage_longer_than_lease(self, workspace: Workspace) -> None:
        ids = IdGenerator()
        job = await _queued_job(workspace, "hb1")
        repo = WorkerRepository(workspace._db, ids)
        lease_seconds = 1  # shorter than the stage below
        stage_duration = 1.6

        # worker A claims the job (leased, lease=1s), then starts the long stage
        claimed = await repo.claim_eligible(worker="worker-a", lease_seconds=lease_seconds)
        assert claimed is not None and claimed.id == job.id

        stage_done = asyncio.Event()

        async def long_stage(ctx: Any) -> dict[str, int]:
            await asyncio.sleep(stage_duration)
            stage_done.set()
            return {"ok": 1}

        engine = JobEngine(ids=ids, repo=repo, retry_policy=RetryPolicy())

        def stages(job_type: str) -> list[tuple[str, Any]]:
            return [("pipeline", long_stage)]

        worker = Worker(
            ids=ids,
            engine=engine,
            stage_provider=stages,
            repo=repo,
            worker_id="worker-a",
            lease_seconds=lease_seconds,
            poll_interval_s=0.05,
        )

        stolen: list[str] = []

        async def thief() -> None:
            """Worker B polls for stealable work for as long as A's stage runs."""
            while not stage_done.is_set():
                async with workspace._db.session() as session, session.begin():
                    b_repo = JobRepository(session, ids)
                    got = await b_repo.claim_eligible(
                        worker="worker-b", lease_seconds=lease_seconds
                    )
                if got is not None:
                    stolen.append(got.id)
                    stage_done.set()  # stop the experiment, job was stolen
                    return
                await asyncio.sleep(0.05)

        loaded = await repo.get(job.id)
        assert loaded is not None

        thief_task = asyncio.create_task(thief())
        result = await engine.run(
            loaded,
            stages("pipeline"),
            services={},
            heartbeat=worker.heartbeat_for(loaded.id),
            heartbeat_interval_s=0.2,
        )
        await thief_task

        assert result.state == JobState.succeeded
        assert stolen == [], (
            f"lease expired mid-stage and worker-b stole the job: {stolen}. "
            "Heartbeat must renew the lease while a long stage executes."
        )

    async def test_lease_expires_at_advances_during_stage(self, workspace: Workspace) -> None:
        """The durable row's lease_expires_at must move forward while the stage runs."""
        ids = IdGenerator()
        job = await _queued_job(workspace, "hb2")
        repo = WorkerRepository(workspace._db, ids)
        lease_seconds = 1

        claimed = await repo.claim_eligible(worker="worker-a", lease_seconds=lease_seconds)
        assert claimed is not None
        initial_expiry = claimed.lease_expires_at
        assert initial_expiry is not None

        observed: list[datetime] = []

        async def long_stage(ctx: Any) -> dict[str, int]:
            for _ in range(6):
                await asyncio.sleep(0.15)
                current = await repo.get(job.id)
                if current is not None and current.lease_expires_at is not None:
                    observed.append(current.lease_expires_at)
            return {"ok": 1}

        engine = JobEngine(ids=ids, repo=repo, retry_policy=RetryPolicy())
        loaded = await repo.get(job.id)
        assert loaded is not None

        worker = Worker(
            ids=ids,
            engine=engine,
            stage_provider=lambda jt: [],
            repo=repo,
            worker_id="worker-a",
            lease_seconds=lease_seconds,
        )
        await engine.run(
            loaded,
            [("pipeline", long_stage)],
            services={},
            heartbeat=worker.heartbeat_for(loaded.id),
            heartbeat_interval_s=0.1,
        )

        assert len(observed) >= 3, "stage observations missing"
        assert _aware(observed[-1]) > _aware(initial_expiry) + timedelta(seconds=0.3), (
            f"lease_expires_at never advanced during the stage "
            f"({initial_expiry} → {observed[-1]}); heartbeat loop is not running"
        )

    async def test_renew_lease_rejects_non_owner(self, workspace: Workspace) -> None:
        """Only the current lease owner may renew a lease."""
        ids = IdGenerator()
        job = await _queued_job(workspace, "hb3")

        async with workspace._db.session() as session, session.begin():
            jrepo = JobRepository(session, ids)
            claimed = await jrepo.claim_eligible(worker="worker-a", lease_seconds=60)
            assert claimed is not None
            before = claimed.lease_expires_at

        # worker B (not the owner) attempts to renew
        async with workspace._db.session() as session, session.begin():
            jrepo = JobRepository(session, ids)
            renewed = await jrepo.renew_lease(job.id, worker="worker-b", lease_seconds=60)
            assert renewed is False, "non-owner must not be able to renew a lease"

        # the owner renews successfully and the expiry moves
        async with workspace._db.session() as session, session.begin():
            jrepo = JobRepository(session, ids)
            renewed = await jrepo.renew_lease(job.id, worker="worker-a", lease_seconds=60)
            assert renewed is True
            current = await jrepo.get(job.id)
            assert current is not None
            assert current.lease_expires_at is not None
            assert before is not None
            assert _aware(current.lease_expires_at) > _aware(before)
            assert current.heartbeat_at is not None

    async def test_worker_tick_renews_heartbeat_between_jobs(self, workspace: Workspace) -> None:
        """Worker._heartbeat keeps a leased job's lease fresh across ticks."""
        ids = IdGenerator()
        job = await _queued_job(workspace, "hb4")

        repo = WorkerRepository(workspace._db, ids)
        worker = Worker(
            ids=ids,
            engine=JobEngine(ids=ids, repo=repo, retry_policy=RetryPolicy()),
            stage_provider=lambda jt: [],
            repo=repo,
            worker_id="worker-a",
            lease_seconds=60,
            poll_interval_s=0.05,
        )

        claimed = await repo.claim_eligible(worker="worker-a", lease_seconds=60)
        assert claimed is not None and claimed.id == job.id

        async with workspace._db.session() as session, session.begin():
            jrepo = JobRepository(session, ids)
            current = await jrepo.get(job.id)
            assert current is not None
            stale = datetime.now(UTC) + timedelta(seconds=30)
            current.lease_expires_at = stale
            await jrepo.save(current)

        await worker._heartbeat(job.id)

        async with workspace._db.session() as session, session.begin():
            jrepo = JobRepository(session, ids)
            current = await jrepo.get(job.id)
            assert current is not None
            assert current.lease_expires_at is not None
            assert _aware(current.lease_expires_at) > _aware(stale), (
                "worker heartbeat did not renew the lease"
            )
