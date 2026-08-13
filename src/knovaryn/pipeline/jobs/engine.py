"""Durable job engine and stage orchestration (spec §7).

The job engine persists every state change, records events, honors budgets and
cooperative cancellation, and checkpoints per-stage results so a restarted job
resumes without repeating completed provider calls (§2.2, §7.2).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from ...domain.errors import BudgetExceededError, KnovarynError
from ...domain.ids import IdGenerator
from ...domain.schemas import Job, JobEvent, JobState
from .budget import BudgetState
from .retry import RetryPolicy, backoff_delay, is_retryable
from .state import StateMachine

StageFn = Callable[["StageContext"], Awaitable[Any]]


class JobEvents(Protocol):
    async def append_event(self, job_id: str, event: JobEvent) -> None: ...

    async def save(self, job: Job) -> None: ...

    async def get(self, job_id: str) -> Job | None: ...

    async def get_events(
        self, job_id: str, *, cursor: int | None = None, limit: int = 100
    ) -> tuple[list[JobEvent], int | None]: ...

    async def record_checkpoint(self, payload: dict[str, Any]) -> None: ...

    async def completed_checkpoints(self, job_id: str) -> list[str]: ...


@dataclass
class StageContext:
    """Passed to every stage function."""

    job: Job
    ids: IdGenerator
    budget: BudgetState
    config: dict[str, Any]  # resolved pipeline config
    cache: dict[str, Any] = field(default_factory=dict)  # per-run in-memory stage results
    checkpoint_store: Any = None  # job repo (durable checkpoints + events)
    checkpoint_sequence: int = 0  # monotonic durable checkpoint counter
    worker_id: str = ""
    stage_version: str = "1"
    services: dict[str, Any] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)

    async def event(
        self,
        message: str,
        *,
        level: str = "info",
        event_type: str = "log",
        stage: str = "",
        payload: dict[str, Any] | None = None,
    ) -> None:
        ev = JobEvent(
            id=self.ids.new(),
            job_id=self.job.id,
            timestamp=datetime.now(UTC),
            level=level,
            event_type=event_type,
            stage=stage or self.job.current_stage or "",
            message=message,
            structured_payload=payload or {},
        )
        await self.checkpoint_store.append_event(self.job.id, ev)

    async def checkpoint(
        self,
        stage: str,
        *,
        key: str = "",
        value: dict[str, Any] | None = None,
        status: str = "completed",
        input_hash: str = "",
        artifact_ids: list[str] | None = None,
        error: str = "",
        poi: Any = None,
        step: int = 0,
    ) -> None:
        """Persist a durable stage checkpoint (spec §12/E2).

        The full checkpoint payload is written to ``job_checkpoints`` so a
        crash + restart resumes from the last committed stage instead of
        repeating provider calls. Payload values are never discarded.
        """
        self.checkpoint_sequence += 1
        now = datetime.now(UTC)
        self.job.current_stage = stage
        payload = {
            "job_id": self.job.id,
            "stage_name": stage,
            "stage_version": self.stage_version,
            "checkpoint_key": key,
            "checkpoint_sequence": self.checkpoint_sequence,
            "status": status,
            "input_hash": input_hash,
            "output_artifact_ids": artifact_ids or [],
            "output_summary": value or {},
            "started_at": self.job.started_at,
            "completed_at": now,
            "worker_id": self.worker_id,
            "error": error,
        }
        await self.checkpoint_store.record_checkpoint(payload)
        await self.checkpoint_store.save(self.job)

    def cancellation_requested(self) -> bool:
        return self.job.cancellation_requested_at is not None


class JobEngine:
    """Executes a list of stages with durability, budgets, and cancellation."""

    def __init__(
        self, *, ids: IdGenerator, repo: JobEvents, retry_policy: RetryPolicy | None = None
    ) -> None:
        self._ids = ids
        self._repo = repo
        self._retry_policy = retry_policy or RetryPolicy()

    async def run(
        self, job: Job, stages: list[tuple[str, StageFn]], *, services: dict[str, Any] | None = None
    ) -> Job:
        sm = StateMachine(job.state)
        stashed = job.input or {}
        budget = _budget_from_config(stashed.get("budget", {}))
        ctx = StageContext(
            job=job,
            ids=self._ids,
            budget=budget,
            config=stashed.get("pipeline", {}) or stashed,
            checkpoint_store=self._repo,
            worker_id=stashed.get("worker_id", ""),
            stage_version=stashed.get("stage_version", "1"),
            services=services or {},
        )
        try:
            sm.transition(JobState.running)
            job.state = JobState.running
            job.started_at = job.started_at or datetime.now(UTC)
            job.current_stage = None
            await self._repo.save(job)

            # durable resume source of truth: committed stage checkpoints survive
            # a crash, so a replacement worker skips recompute (WP E2/P0-5).
            ctx.extras["completed_stages"] = set(await self._repo.completed_checkpoints(job.id))

            for idx, (name, fn) in enumerate(stages):
                if ctx.cancellation_requested():
                    break
                if (
                    ctx.extras.get("completed_stages", set())
                    and name in ctx.extras["completed_stages"]
                ):
                    # resume path: stage already checkpoint-complete
                    job.current_stage = name
                    continue
                job.current_stage = name
                job.progress_total = len(stages)
                job.progress_current = idx
                ctx.checkpoint_store = self._repo
                await self._repo.save(job)
                # K4: job-stage duration histogram (labelled by stage name).
                from ...infrastructure.telemetry.metrics import Timer, get_registry

                with Timer(get_registry(), "knovaryn_job_stage_duration_seconds", {"stage": name}):
                    await self._execute_with_retry(ctx, name, fn)
                if name not in ctx.extras["completed_stages"]:
                    # durably commit the stage so a crash here never re-runs it
                    await ctx.checkpoint(
                        name,
                        key=f"{name}:done",
                        value={"stage": name},
                    )
                    ctx.extras["completed_stages"].add(name)

            if job.cancellation_requested_at is not None:
                job.state = JobState.cancelled
            else:
                sm.transition(JobState.succeeded)
                job.state = JobState.succeeded
            job.finished_at = datetime.now(UTC)
            job.actual_cost = budget.spent_cost_usd
            await self._repo.save(job)
            return job
        except asyncio.CancelledError:
            job.state = JobState.cancelling
            job.cancellation_requested_at = datetime.now(UTC)
            await self._repo.save(job)
            raise
        except BudgetExceededError as exc:
            job.state = JobState.paused
            job.error_code = exc.code
            job.error_summary = exc.message
            job.finished_at = datetime.now(UTC)
            await self._repo.save(job)
            return job
        except KnovarynError as exc:
            job.state = JobState.failed
            job.error_code = exc.code
            job.error_summary = exc.message
            job.finished_at = datetime.now(UTC)
            await self._repo.save(job)
            return job
        except Exception as exc:  # noqa: BLE001 - upper layers classify
            job.state = JobState.failed
            job.error_code = "unhandled"
            job.error_summary = str(exc)
            job.finished_at = datetime.now(UTC)
            await self._repo.save(job)
            return job

    async def _execute_with_retry(self, ctx: StageContext, name: str, fn: StageFn) -> Any:
        attempt = 0
        while True:
            try:
                ctx.job.attempt_count = attempt + 1
                result = await fn(ctx)
                await ctx.event(f"stage {name} complete", event_type="stage_complete", stage=name)
                return result
            except asyncio.CancelledError:
                raise
            except BudgetExceededError:
                raise
            except Exception as exc:  # noqa: BLE001
                if not is_retryable(
                    exc, max_attempts=self._retry_policy.max_attempts, attempt=attempt
                ):
                    raise
                # K4: retry count by stage (retryable transient failure).
                from ...infrastructure.telemetry.metrics import get_registry

                get_registry().inc("knovaryn_job_stage_retries_total", labels={"stage": name})
                await ctx.event(
                    f"stage {name} retrying ({attempt + 1})", level="warning", stage=name
                )
                attempt += 1
                delay = backoff_delay(self._retry_policy, attempt).delay_s
                # cooperative cancellation check during backoff
                for _ in range(max(1, int(delay / 0.1))):
                    if ctx.cancellation_requested():
                        raise asyncio.CancelledError() from None
                    await asyncio.sleep(0.1)


def _budget_from_config(cfg: dict[str, Any]) -> BudgetState:
    return BudgetState(
        maximum_cost_usd=cfg.get("maximum_cost_usd", 50.0),
        maximum_calls=cfg.get("maximum_calls", 10000),
        maximum_input_tokens=cfg.get("maximum_input_tokens"),
        maximum_output_tokens=cfg.get("maximum_output_tokens"),
        maximum_duration_s=cfg.get("maximum_duration_s"),
        maximum_examples=cfg.get("maximum_examples", 2500),
        per_provider_rate=cfg.get("per_provider_rate", {}),
    )


# Convenience: a stage-completion tracker the orchestrator updates between runs
class CheckpointTracker:
    """Tracks completed stages in job extras for crash recovery (resume)."""

    def __init__(self, job: Job) -> None:
        self.completed: set[str] = set(job.input.get("completed_stages", []))

    def mark(self, name: str) -> None:
        self.completed.add(name)

    def to_extras(self) -> dict[str, Any]:
        return {"completed_stages": set(self.completed)}

    def persisted(self) -> list[str]:
        return sorted(self.completed)
