"""Regression tests: expired lease reclaim (defect 4.8, spec §7.3, §12/E4).

A worker that dies mid-run leaves its job row in ``leased``/``running`` with a
lease that eventually expires. That job is orphaned forever unless
``claim_eligible`` reclaims expired-lease jobs in those states — a replacement
worker's poll loop must pick it up with no manual state surgery.
"""

from __future__ import annotations

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

_SAMPLE = "# Doc\n\nSome content for the durable pipeline."


@pytest.fixture
async def workspace(tmp_path: Path) -> Workspace:
    db = tmp_path / "knovaryn-lease.db"
    ws = Workspace(database_url=f"sqlite+aiosqlite:///{db}", principal="test")
    await ws.open()
    yield ws
    await ws.close()


async def _queue_job(ws: Workspace, slug: str) -> Any:
    proj = await ws.create_project(slug=slug, display_name="Lease Widgets")
    await ws.add_source(
        project_id=proj.id,
        original_name="doc.md",
        media_type="text/markdown",
        content=_SAMPLE,
    )
    return await ws.start_pipeline(project_id=proj.id, task_family_proportions={})


def _repo(ws: Workspace, ids: IdGenerator) -> JobRepository:
    return JobRepository(ws._db.session(), ids)  # type: ignore[arg-type]


class TestExpiredLeaseReclaim:
    """Expired running/leased jobs must be reclaimable by a new worker."""

    async def test_expired_running_lease_reclaimed(self, workspace: Workspace) -> None:
        """Worker A dies mid-run (state=running, lease expired) → B reclaims."""
        ids = IdGenerator()
        job = await _queue_job(workspace, "lease-running")

        async with workspace._db.session() as session, session.begin():
            repo = JobRepository(session, ids)
            claimed = await repo.claim_eligible(worker="worker-a", lease_seconds=300)
            assert claimed is not None and claimed.id == job.id
            # engine moves leased → running, then the process dies
            claimed.state = JobState.running
            claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await repo.save(claimed)

        async with workspace._db.session() as session, session.begin():
            repo = JobRepository(session, ids)
            reclaimed = await repo.claim_eligible(worker="worker-b", lease_seconds=300)
            assert reclaimed is not None, (
                "expired RUNNING lease must be reclaimable — job was orphaned"
            )
            assert reclaimed.id == job.id
            assert reclaimed.state == JobState.leased
            assert reclaimed.lease_owner == "worker-b"
            assert reclaimed.lease_expires_at is not None
            assert reclaimed.lease_expires_at > datetime.now(UTC)

    async def test_expired_leased_state_reclaimed(self, workspace: Workspace) -> None:
        """Worker A claims (leased) then dies before running → B reclaims."""
        ids = IdGenerator()
        job = await _queue_job(workspace, "lease-claimed")

        async with workspace._db.session() as session, session.begin():
            repo = JobRepository(session, ids)
            claimed = await repo.claim_eligible(worker="worker-a", lease_seconds=300)
            assert claimed is not None
            claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await repo.save(claimed)

        async with workspace._db.session() as session, session.begin():
            repo = JobRepository(session, ids)
            reclaimed = await repo.claim_eligible(worker="worker-b", lease_seconds=300)
            assert reclaimed is not None, "expired LEASED job must be reclaimable"
            assert reclaimed.id == job.id
            assert reclaimed.lease_owner == "worker-b"

    async def test_live_lease_not_stolen(self, workspace: Workspace) -> None:
        """A job whose lease is still valid must NOT be claimable by another worker."""
        ids = IdGenerator()
        job = await _queue_job(workspace, "lease-live")

        async with workspace._db.session() as session, session.begin():
            repo = JobRepository(session, ids)
            claimed = await repo.claim_eligible(worker="worker-a", lease_seconds=300)
            assert claimed is not None

        async with workspace._db.session() as session, session.begin():
            repo = JobRepository(session, ids)
            stolen = await repo.claim_eligible(worker="worker-b", lease_seconds=300)
            assert stolen is None, "live lease must not be stolen"

        # and the job is untouched
        async with workspace._db.session() as session, session.begin():
            repo = JobRepository(session, ids)
            current = await repo.get(job.id)
            assert current is not None
            assert current.state == JobState.leased
            assert current.lease_owner == "worker-a"

    async def test_reclaimed_job_resumes_through_engine(self, workspace: Workspace) -> None:
        """Reclaim feeds straight into a normal engine run (no manual state fixup)."""
        ids = IdGenerator()
        await _queue_job(workspace, "lease-resume")

        async with workspace._db.session() as session, session.begin():
            repo = JobRepository(session, ids)
            claimed = await repo.claim_eligible(worker="worker-a", lease_seconds=300)
            assert claimed is not None
            claimed.state = JobState.running
            claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await repo.save(claimed)

        async with workspace._db.session() as session, session.begin():
            repo = JobRepository(session, ids)
            reclaimed = await repo.claim_eligible(worker="worker-b", lease_seconds=300)
            assert reclaimed is not None

        ran: list[str] = []

        async def stage(ctx: Any) -> dict[str, int]:
            ran.append(ctx.job.current_stage or "stage")
            return {"ok": 1}

        engine = JobEngine(ids=ids, repo=_EngineRepo(workspace, ids), retry_policy=RetryPolicy())
        result = await engine.run(
            reclaimed, [("only", stage)], services={"job.input": reclaimed.input}
        )
        assert result.state == JobState.succeeded
        assert ran == ["only"]

    async def test_reclaim_resets_lease_ownership_atomically(self, workspace: Workspace) -> None:
        """Reclaim must reassign lease_owner and bump attempt_count."""
        ids = IdGenerator()
        await _queue_job(workspace, "lease-attempt")

        async with workspace._db.session() as session, session.begin():
            repo = JobRepository(session, ids)
            first = await repo.claim_eligible(worker="worker-a", lease_seconds=300)
            assert first is not None
            attempts_after_first = first.attempt_count
            first.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await repo.save(first)

        async with workspace._db.session() as session, session.begin():
            repo = JobRepository(session, ids)
            second = await repo.claim_eligible(worker="worker-b", lease_seconds=300)
            assert second is not None
            assert second.attempt_count == attempts_after_first + 1
            assert second.lease_owner == "worker-b"


class _EngineRepo:
    """Per-op session adapter over the workspace DB for the engine protocol."""

    def __init__(self, ws: Workspace, ids: IdGenerator) -> None:
        self._ws = ws
        self._ids = ids

    async def _op(self, method: str, *args: Any, **kwargs: Any) -> Any:
        from knovaryn.infrastructure.database.repositories import JobRepository as JR

        async with self._ws._db.session() as session, session.begin():
            repo = JR(session, self._ids)
            return await getattr(repo, method)(*args, **kwargs)

    async def append_event(self, job_id: str, event: Any) -> None:
        await self._op("append_event", job_id, event)

    async def save(self, job: Any) -> None:
        await self._op("save", job)

    async def get(self, job_id: str) -> Any:
        return await self._op("get", job_id)

    async def get_events(
        self, job_id: str, *, cursor: int | None = None, limit: int = 100
    ) -> tuple[list[Any], int | None]:
        return await self._op("get_events", job_id, cursor=cursor, limit=limit)

    async def record_checkpoint(self, payload: dict[str, Any]) -> None:
        await self._op("record_checkpoint", payload)

    async def completed_checkpoints(self, job_id: str) -> list[str]:
        return await self._op("completed_checkpoints", job_id)
