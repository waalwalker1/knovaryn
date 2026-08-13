"""Worker (spec §7.3).

Leases one eligible job, renews heartbeats, runs the pipeline, and handles
SIGTERM shutdown: stop accepting work, checkpoint, and release/let lease expire.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from ...domain.ids import IdGenerator
from ...domain.schemas import JobState
from .engine import CheckpointTracker, JobEngine

log = logging.getLogger("knovaryn.worker")

StageProvider = Callable[[str], list[tuple[str, Callable[..., Any]]]]


class Worker:
    def __init__(
        self,
        *,
        ids: IdGenerator,
        engine: JobEngine,
        stage_provider: StageProvider,
        repo: Any,
        worker_id: str = "w1",
        lease_seconds: int = 300,
        poll_interval_s: float = 1.0,
    ) -> None:
        self._ids = ids
        self._engine = engine
        self._stage_provider = stage_provider
        self._repo = repo
        self.worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._poll = poll_interval_s
        self._running: set[str] = set()
        self._stop = asyncio.Event()
        self._asyncio_done = None

    def install_signal_handlers(self, loop: asyncio.AbstractEventLoop) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            with suppress(NotImplementedError):  # pragma: no cover - windows
                loop.add_signal_handler(sig, self.request_shutdown)

    def request_shutdown(self) -> None:
        log.info("worker %s shutting down", self.worker_id)
        self._stop.set()

    async def run_forever(self) -> None:
        log.info("worker %s online (lease=%ss)", self.worker_id, self._lease_seconds)
        while not self._stop.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                log.exception("worker tick error")
            await asyncio.sleep(self._poll)
        log.info("worker %s drained and stopped", self.worker_id)

    async def _tick(self) -> None:
        # renew heartbeats for jobs we own
        for jid in list(self._running):
            await self._heartbeat(jid)
        # reclaim expired leases / claim new
        job = await self._repo.claim_eligible(
            worker=self.worker_id, lease_seconds=self._lease_seconds
        )
        if job is None:
            return
        self._running.add(job.id)
        try:
            stages = self._stage_provider(job.job_type)
            tracker = CheckpointTracker(job)
            job.input["completed_stages"] = tracker.persisted()
            result = await self._engine.run(job, stages, services={"job.input": job.input})
            if result.state in (
                JobState.succeeded,
                JobState.failed,
                JobState.cancelled,
                JobState.paused,
            ):
                self._running.discard(job.id)
        except asyncio.CancelledError:
            self._running.discard(job.id)
            raise
        except Exception:  # noqa: BLE001
            log.exception("worker job %s failed unexpectedly", job.id)
            self._running.discard(job.id)

    async def _heartbeat(self, job_id: str) -> None:
        job = await self._repo.get(job_id)
        if job is None or job.state not in (JobState.leased, JobState.running):
            self._running.discard(job_id)
            return
        now = datetime.now(UTC)
        if job.lease_owner != self.worker_id:
            self._running.discard(job_id)
            return
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=self._lease_seconds)
        await self._repo.save(job)


class WorkerRepository:
    """Durable job repository for the worker poll loop (spec §7.3, §12/E2).

    ``Worker._tick`` and the :class:`JobEngine` operate over an unbounded number
    of claim/heartbeat/resume cycles while the worker is idle between polls, so
    no single long-lived transaction may be held open across the loop. This
    adapter wraps a :class:`Database` and runs each operation in its own
    session/transaction — every claim, heartbeat, event, and durable checkpoint
    is independently committed and survives a crash. It satisfies both the
    ``Worker``'s repo contract and the engine's ``JobEvents`` protocol.
    """

    def __init__(self, db: Any, ids: IdGenerator) -> None:
        self._db = db
        self._ids = ids

    async def _op(self, method: str, *args: Any, **kwargs: Any) -> Any:
        from ...infrastructure.database.repositories import JobRepository

        async with self._db.session() as session, session.begin():
            repo = JobRepository(session, self._ids)
            op = getattr(repo, method)
            return await op(*args, **kwargs)

    # -- worker repo contract -------------------------------------------------
    async def claim_eligible(self, *, worker: str, lease_seconds: int = 300) -> Any:
        return await self._op("claim_eligible", worker=worker, lease_seconds=lease_seconds)

    async def get(self, job_id: str) -> Any:
        return await self._op("get", job_id)

    async def save(self, job: Any) -> None:
        await self._op("save", job)

    # -- engine JobEvents protocol --------------------------------------------
    async def append_event(self, job_id: str, event: Any) -> None:
        await self._op("append_event", job_id, event)

    async def get_events(
        self, job_id: str, *, cursor: int | None = None, limit: int = 100
    ) -> tuple[list[Any], int | None]:
        return await self._op("get_events", job_id, cursor=cursor, limit=limit)  # type: ignore[no-any-return]

    async def record_checkpoint(self, payload: dict[str, Any]) -> None:
        await self._op("record_checkpoint", payload)

    async def completed_checkpoints(self, job_id: str) -> list[str]:
        return await self._op("completed_checkpoints", job_id)  # type: ignore[no-any-return]


__all__ = ["Worker", "WorkerRepository"]
