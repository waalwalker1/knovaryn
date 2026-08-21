"""Regression tests: external cancellation with bounded latency (spec §7.2).

An external cancel (REST ``POST /jobs/{id}:cancel`` equivalent) stamps
``cancellation_requested_at`` on the job row. The engine must observe it with
bounded latency: cooperatively within a stage, immediately at stage boundaries,
and the job must reach the TERMINAL ``cancelled`` state — never stuck in
non-terminal ``cancelling``.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from knovaryn.application.workspace import Workspace
from knovaryn.domain.ids import IdGenerator
from knovaryn.domain.schemas import JobState
from knovaryn.pipeline.jobs.engine import JobEngine
from knovaryn.pipeline.jobs.retry import RetryPolicy
from knovaryn.pipeline.jobs.state import is_terminal

_SAMPLE = "# Doc\n\nCancellation test content."


@pytest.fixture
async def workspace(tmp_path: Path) -> Workspace:
    db = tmp_path / "knovaryn-cancel.db"
    ws = Workspace(database_url=f"sqlite+aiosqlite:///{db}", principal="test")
    await ws.open()
    yield ws
    await ws.close()


class _EngineRepo:
    """Per-op session adapter satisfying the engine's JobEvents protocol."""

    def __init__(self, ws: Workspace, ids: IdGenerator) -> None:
        self._ws = ws
        self._ids = ids

    async def _op(self, method: str, *args: Any, **kwargs: Any) -> Any:
        from knovaryn.infrastructure.database.repositories import JobRepository

        async with self._ws._db.session() as session, session.begin():
            repo = JobRepository(session, self._ids)
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

    async def claim_eligible(self, *, worker: str, lease_seconds: int = 300) -> Any:
        return await self._op("claim_eligible", worker=worker, lease_seconds=lease_seconds)


class TestExternalCancel:
    """External cancellation must have bounded latency and a terminal state."""

    async def test_cancellation_during_generation(
        self, workspace: Workspace, tmp_path: Path
    ) -> None:
        """Cancel stamped mid-generation stops the stage within bounded latency."""
        ids = IdGenerator()
        proj = await workspace.create_project(slug="cancel-mid", display_name="Cancel")
        await workspace.add_source(
            project_id=proj.id,
            original_name="doc.md",
            media_type="text/markdown",
            content=_SAMPLE,
        )
        job = await workspace.start_pipeline(project_id=proj.id, task_family_proportions={})

        ran: list[str] = []
        cancel_stamp: list[float] = []

        async def generate(ctx: Any) -> dict[str, int]:
            """Long cooperative stage: re-reads the durable cancel flag every 10 ms.

            The external cancel lands on the DATABASE row (that is what the
            REST/MCP cancel endpoint does), so the stage must refresh — the
            in-memory job object never sees it otherwise.
            """
            ran.append("generate")
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if await ctx.refresh_cancellation():
                    raise asyncio.CancelledError
                await asyncio.sleep(0.01)
            return {"examples": 1}

        async def export(ctx: Any) -> dict[str, int]:
            ran.append("export")
            return {"exported": 1}

        async def external_cancel() -> None:
            """Control plane: stamp the cancel flag ~100 ms into the stage."""
            await asyncio.sleep(0.1)
            async with workspace._db.session() as session, session.begin():
                from knovaryn.infrastructure.database.repositories import JobRepository

                repo = JobRepository(session, ids)
                current = await repo.get(job.id)
                assert current is not None
                current.cancellation_requested_at = datetime.now(UTC)
                await repo.save(current)
            cancel_stamp.append(time.monotonic())

        engine = JobEngine(ids=ids, repo=_EngineRepo(workspace, ids), retry_policy=RetryPolicy())

        # the worker claims the job before running it (queued → leased), exactly
        # like Worker._tick; the control plane then mutates the DB row the
        # worker does NOT hold in memory — the real external-cancel path.
        repo = _EngineRepo(workspace, ids)
        claimed = await repo.claim_eligible(worker="worker-a", lease_seconds=300)
        assert claimed is not None and claimed.id == job.id
        loaded = claimed

        cancel_task = asyncio.create_task(external_cancel())
        started = time.monotonic()
        result = await engine.run(loaded, [("generate", generate), ("export", export)], services={})
        latency = time.monotonic() - started
        await cancel_task

        assert cancel_stamp, "external cancel never fired"
        assert result.state == JobState.cancelled, (
            f"requested cancellation must end TERMINAL cancelled, got {result.state}"
        )
        assert is_terminal(result.state)
        assert "generate" in ran
        assert "export" not in ran, "stages after the cancel point must never run"
        assert latency < 2.0, f"cancellation latency unbounded: {latency:.2f}s (stage allows 5s)"
        assert result.finished_at is not None

    async def test_cancel_before_first_stage_runs_nothing(self, workspace: Workspace) -> None:
        """A cancel stamped while queued: engine runs zero stages, ends cancelled."""
        ids = IdGenerator()
        proj = await workspace.create_project(slug="cancel-early", display_name="Cancel")
        await workspace.add_source(
            project_id=proj.id,
            original_name="doc.md",
            media_type="text/markdown",
            content=_SAMPLE,
        )
        await workspace.start_pipeline(project_id=proj.id, task_family_proportions={})

        repo = _EngineRepo(workspace, ids)
        loaded = await repo.claim_eligible(worker="worker-a", lease_seconds=300)
        assert loaded is not None
        loaded.cancellation_requested_at = datetime.now(UTC)

        ran: list[str] = []

        async def stage(ctx: Any) -> dict[str, int]:
            ran.append("stage")
            return {}

        engine = JobEngine(ids=ids, repo=_EngineRepo(workspace, ids), retry_policy=RetryPolicy())
        result = await engine.run(loaded, [("s1", stage), ("s2", stage)], services={})

        assert result.state == JobState.cancelled
        assert ran == [], "no stage may run once cancellation is already requested"

    async def test_cancel_between_stages_skips_rest(self, workspace: Workspace) -> None:
        """Cancel stamped during stage 2: stage 3+ never run, 1–2 stay checkpointed."""
        ids = IdGenerator()
        proj = await workspace.create_project(slug="cancel-midway", display_name="Cancel")
        await workspace.add_source(
            project_id=proj.id,
            original_name="doc.md",
            media_type="text/markdown",
            content=_SAMPLE,
        )
        job = await workspace.start_pipeline(project_id=proj.id, task_family_proportions={})

        ran: list[str] = []

        async def make_stage(name: str) -> Any:
            async def stage(ctx: Any) -> dict[str, int]:
                ran.append(name)
                if name == "two":
                    # control plane stamps the cancel while stage two runs
                    async with workspace._db.session() as session, session.begin():
                        from knovaryn.infrastructure.database.repositories import JobRepository

                        repo = JobRepository(session, ids)
                        current = await repo.get(job.id)
                        assert current is not None
                        current.cancellation_requested_at = datetime.now(UTC)
                        await repo.save(current)
                    # the in-memory job object the engine holds must observe it
                    ctx.job.cancellation_requested_at = datetime.now(UTC)
                return {}

            return stage

        loaded = await _EngineRepo(workspace, ids).claim_eligible(
            worker="worker-a", lease_seconds=300
        )
        assert loaded is not None
        engine = JobEngine(ids=ids, repo=_EngineRepo(workspace, ids), retry_policy=RetryPolicy())
        stages = [
            ("one", await make_stage("one")),
            ("two", await make_stage("two")),
            ("three", await make_stage("three")),
        ]
        result = await engine.run(loaded, stages, services={})

        assert result.state == JobState.cancelled
        assert ran == ["one", "two"], f"stage three must not run after cancel, ran={ran}"
        completed = await _EngineRepo(workspace, ids).completed_checkpoints(job.id)
        assert "one" in completed and "two" in completed
        assert "three" not in completed
