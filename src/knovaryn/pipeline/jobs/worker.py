"""Worker (spec §7.3).

Leases one eligible job, renews heartbeats, runs the pipeline, and handles
SIGTERM shutdown: stop accepting work, checkpoint, and release/let lease expire.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from contextlib import suppress
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
            result = await self._engine.run(
                job,
                stages,
                services={"job.input": job.input},
                # renew the lease while stages execute — a single stage that
                # outlives the lease must not be stolen by another worker
                heartbeat=self.heartbeat_for(job.id),
                heartbeat_interval_s=max(1.0, min(self._lease_seconds / 3.0, 30.0)),
            )
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

    def heartbeat_for(self, job_id: str) -> Callable[[], Awaitable[None]]:
        """A renewal callback for the engine's heartbeat loop (spec §7.3).

        Passed into ``JobEngine.run`` so the lease is re-extended concurrently
        while a long stage executes, not only between worker ticks.
        """

        async def _renew() -> None:
            renewed = await self._repo.renew_lease(
                job_id, worker=self.worker_id, lease_seconds=self._lease_seconds
            )
            if not renewed:
                # lost ownership or the job is no longer leasable — stop tracking
                self._running.discard(job_id)

        return _renew

    async def _heartbeat(self, job_id: str) -> None:
        renewed = await self._repo.renew_lease(
            job_id, worker=self.worker_id, lease_seconds=self._lease_seconds
        )
        if not renewed:
            self._running.discard(job_id)


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

    async def renew_lease(self, job_id: str, *, worker: str, lease_seconds: int = 300) -> bool:
        result = await self._op("renew_lease", job_id, worker=worker, lease_seconds=lease_seconds)
        return bool(result)

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


class ModelCallLedgerRepository:
    """Per-op session adapter exposing the ``model_calls`` ledger to the gateway.

    Durable provider-call dedup (spec §11.5): the gateway consults this ledger
    on a call-cache miss, so a resumed job never re-invokes a paid call whose
    fingerprint was already recorded — and never writes a duplicate cost event.
    Same session discipline as :class:`WorkerRepository`: every record/lookup
    commits independently and survives a crash.
    """

    def __init__(self, db: Any, ids: IdGenerator) -> None:
        self._db = db
        self._ids = ids

    async def _op(self, method: str, *args: Any, **kwargs: Any) -> Any:
        from ...infrastructure.database.repositories import ModelCallRepository

        async with self._db.session() as session, session.begin():
            repo = ModelCallRepository(session, self._ids)
            return await getattr(repo, method)(*args, **kwargs)

    async def record(self, call: dict[str, Any]) -> None:
        await self._op("record", call)

    async def get_by_fingerprint(self, job_id: str, fingerprint: str) -> Any:
        return await self._op("get_by_fingerprint", job_id, fingerprint)


__all__ = ["ModelCallLedgerRepository", "Worker", "WorkerRepository"]
