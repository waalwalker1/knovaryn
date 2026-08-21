"""Telemetry (spec §22) and the offline worker (spec §7.3) + retry (spec §7.4).

Covers metrics registry, trace context, structured logging, the Worker lease/
heartbeat/tick loop with a fake repository, and retry classification/backoff.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from knovaryn.domain.errors import BudgetExceededError, PolicyBlockError, ProviderError
from knovaryn.domain.schemas import JobState
from knovaryn.infrastructure.models.secrets import redact
from knovaryn.infrastructure.telemetry.logging import ContentGuard, get_logger
from knovaryn.infrastructure.telemetry.metrics import MetricsRegistry, Timer, get_registry
from knovaryn.infrastructure.telemetry.tracing import (
    current_span_name,
    flush_trace,
    start_span,
)
from knovaryn.pipeline.jobs.retry import (
    BackoffResult,
    RetryPolicy,
    backoff_delay,
    classify_failure,
    is_retryable,
    state_for_exc,
)
from knovaryn.pipeline.jobs.worker import Worker

# ---------------------------------------------------------------------------
# §22.2 — metrics
# ---------------------------------------------------------------------------


def test_metrics_inc_and_snapshot() -> None:
    r = MetricsRegistry()
    r.inc("jobs.total")
    r.inc("jobs.total", 3, labels={"kind": "sft"})
    snap = r.snapshot()
    assert snap["counters"]["jobs.total"] == 1
    assert snap["counters"]['jobs.total{kind="sft"}'] == 3


def test_metrics_gauge_and_histogram() -> None:
    r = MetricsRegistry()
    r.set_gauge("mem", 42.0)
    r.observe("lat", 1.0)
    r.observe("lat", 3.0)
    snap = r.snapshot()
    assert snap["gauges"]["mem"] == 42.0
    h = snap["histograms"]["lat"]
    assert h["count"] == 2
    assert h["sum"] == 4.0
    assert h["mean"] == 2.0


def test_metrics_histogram_empty_mean_zero() -> None:
    r = MetricsRegistry()
    snap = r.snapshot()
    assert snap["histograms"] == {}


def test_metrics_render_prometheus() -> None:
    r = MetricsRegistry()
    r.inc("a.count")
    r.set_gauge("b.g", 1.5)
    out = r.render_prometheus()
    assert "# TYPE a.count counter" in out
    assert "a.count 1" in out
    assert "# TYPE b.g gauge" in out
    assert "b.g 1.5" in out
    assert out.endswith("\n")


def test_metrics_key_with_labels_sorted() -> None:
    r = MetricsRegistry()
    r.inc("k", 1, labels={"z": "1", "a": "2"})
    assert 'k{a="2",z="1"}' in r.snapshot()["counters"]


def test_get_registry_singleton() -> None:
    assert get_registry() is get_registry()


def test_timer_observes_duration() -> None:
    r = MetricsRegistry()
    with Timer(r, "dur"):
        pass
    assert r.snapshot()["histograms"]["dur"]["count"] == 1


# ---------------------------------------------------------------------------
# §22.3 — tracing
# ---------------------------------------------------------------------------


def test_trace_flat_span_sets_current() -> None:
    flush_trace()
    with start_span("root") as sp:
        assert current_span_name() == "root"
        assert sp._span is not None
    assert current_span_name() is None
    assert sp._span.duration_ms is not None


def test_trace_nested_spans() -> None:
    flush_trace()
    with start_span("outer"):
        with start_span("inner"):
            assert current_span_name() == "inner"
        assert current_span_name() == "outer"


def test_trace_attributes_attached() -> None:
    flush_trace()
    with start_span("s", attributes={"k": "v"}) as sp:
        assert sp._span.attributes["k"] == "v"


def test_flush_trace_resets_current() -> None:
    flush_trace()
    assert current_span_name() is None


# ---------------------------------------------------------------------------
# §22.1 — logging
# ---------------------------------------------------------------------------


def test_get_logger_returns_bound_logger() -> None:
    logger = get_logger("knovaryn.test")
    assert hasattr(logger, "info")


def test_content_guard_default_off() -> None:
    assert ContentGuard().allow() is False


def test_content_guard_explicit_on() -> None:
    assert ContentGuard(enabled=True).allow() is True


def test_redact_used_with_logger_no_raise() -> None:
    logger = get_logger("knovaryn.sec")
    val = redact("abcdefghijklmnop")
    logger.info("token %s", val)  # never logs raw


# ---------------------------------------------------------------------------
# §7.4 — retry
# ---------------------------------------------------------------------------


class _ProviderErr(ProviderError):
    pass


class _NonRetryable(ProviderError):
    retryable = False


def test_classify_failure_budget() -> None:
    assert classify_failure(BudgetExceededError("budget")) == "budget_exhausted"


def test_classify_failure_policy() -> None:
    assert classify_failure(PolicyBlockError("blocked")) == "policy_block"


def test_classify_failure_provider_retryable() -> None:
    e = _ProviderErr("boom", retryable=True)
    assert classify_failure(e) == "provider"


def test_classify_failure_provider_non_retryable() -> None:
    assert classify_failure(_NonRetryable("boom", retryable=False)) == "provider_non_retryable"


def test_classify_failure_transient_timeout() -> None:
    class TimeoutError_(Exception):
        pass

    assert classify_failure(TimeoutError_("timeout while reading")) == "transient"


def test_classify_failure_plain() -> None:
    assert classify_failure(ValueError("boom")) == "worker_failure"


def test_is_retryable_never_budget_or_policy() -> None:
    assert is_retryable(BudgetExceededError("budget")) is False
    assert is_retryable(PolicyBlockError("blocked")) is False


def test_is_retryable_provider_within_attempts() -> None:
    assert is_retryable(_ProviderErr("boom", retryable=True), attempt=0) is True
    assert is_retryable(_ProviderErr("boom", retryable=True), max_attempts=1, attempt=1) is False
    assert is_retryable(_NonRetryable("boom", retryable=False)) is False


def test_is_retryable_transient_within_attempts() -> None:
    assert is_retryable(RuntimeError("connection refused"), attempt=0) is True
    assert is_retryable(RuntimeError("connection refused"), max_attempts=1, attempt=1) is False


def test_backoff_delay_uses_retry_after_header() -> None:
    p = RetryPolicy(max_delay_s=10)
    res = backoff_delay(p, 1, retry_after_header="3.0")
    assert isinstance(res, BackoffResult)
    assert res.delay_s == 3.0
    assert res.retry_after == "3.0"


def test_backoff_delay_caps_retry_after() -> None:
    p = RetryPolicy(max_delay_s=5)
    res = backoff_delay(p, 1, retry_after_header="999")
    assert res.delay_s == 5.0


def test_backoff_delay_ignores_bad_header() -> None:
    p = RetryPolicy(base_delay_s=1, max_delay_s=60)
    res = backoff_delay(p, 0, retry_after_header="not-a-number")
    assert 0.0 <= res.delay_s <= 1.0


def test_backoff_delay_bounded_jitter() -> None:
    p = RetryPolicy(base_delay_s=2, multiplier=2, max_delay_s=100)
    res = backoff_delay(p, 3)
    # cap = 2 * 2**3 = 16
    assert 0.0 <= res.delay_s <= 16.0


def test_state_for_exc_paused_vs_failed() -> None:
    assert state_for_exc(BudgetExceededError("budget")) == JobState.paused
    assert state_for_exc(PolicyBlockError("blocked")) == JobState.paused
    assert state_for_exc(ValueError("x")) == JobState.failed


# ---------------------------------------------------------------------------
# §7.3 — worker
# ---------------------------------------------------------------------------


class FakeRepo:
    def __init__(self) -> None:
        self.jobs: dict[str, SimpleNamespace] = {}
        self.claim_result = None
        self.saved: list[SimpleNamespace] = []
        self.renewed: list[str] = []

    async def claim_eligible(self, *, worker: str, lease_seconds: int) -> SimpleNamespace | None:
        return self.claim_result

    async def get(self, job_id: str):
        return self.jobs.get(job_id)

    async def save(self, job) -> None:
        self.saved.append(job)

    async def renew_lease(self, job_id: str, *, worker: str, lease_seconds: int) -> bool:
        """Ownership-guarded renewal, mirroring JobRepository.renew_lease."""
        job = self.jobs.get(job_id)
        if job is None or getattr(job, "lease_owner", None) != worker:
            return False
        if job.state not in (JobState.leased, JobState.running):
            return False
        now = datetime.now(UTC)
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        self.renewed.append(job_id)
        return True


class FakeEngine:
    def __init__(self, result=None, exc: Exception | None = None) -> None:
        self._result = result
        self._exc = exc
        self.runs = 0

    async def run(self, job, stages, services=None, **kwargs):
        self.runs += 1
        if self._exc:
            raise self._exc
        return self._result


def _job(job_id="j1", state=JobState.running, job_type="sft", owner="w1"):
    return SimpleNamespace(
        id=job_id,
        job_type=job_type,
        input={"completed_stages": []},
        state=state,
        lease_owner=owner,
        heartbeat_at=None,
        lease_expires_at=None,
    )


def _worker(repo, engine):
    return Worker(
        ids=SimpleNamespace(new_handle=lambda p: f"{p}1"),
        engine=engine,
        stage_provider=lambda jt: [],
        repo=repo,
        worker_id="w1",
        lease_seconds=300,
        poll_interval_s=0.01,
    )


def test_worker_tick_no_job_to_claim() -> None:
    repo = FakeRepo()
    w = _worker(repo, FakeEngine(result=_job()))
    asyncio.run(w._tick())
    assert repo.saved == []


def test_worker_tick_runs_job_to_success() -> None:
    repo = FakeRepo()
    engine = FakeEngine(result=SimpleNamespace(state=JobState.succeeded))
    job = _job()
    repo.claim_result = job
    w = _worker(repo, engine)
    asyncio.run(w._tick())
    assert engine.runs == 1
    assert job.id not in w._running
    assert job.input["completed_stages"] == []


def test_worker_tick_engine_error_discards() -> None:
    repo = FakeRepo()
    engine = FakeEngine(exc=RuntimeError("boom"))
    job = _job()
    repo.claim_result = job
    w = _worker(repo, engine)
    asyncio.run(w._tick())  # no exception propagates
    assert job.id not in w._running


def test_worker_run_forever_stops_on_shutdown() -> None:
    repo = FakeRepo()
    w = _worker(repo, FakeEngine(result=_job()))

    async def drive() -> bool:
        task = asyncio.ensure_future(w.run_forever())
        w.request_shutdown()
        await task
        return True

    assert asyncio.run(drive()) is True


def test_worker_heartbeat_discards_non_owned_or_non_leased() -> None:
    repo = FakeRepo()
    w = _worker(repo, FakeEngine())
    # not leased -> discarded
    repo.jobs["j1"] = _job(state=JobState.queued, owner="w1")
    w._running.add("j1")
    asyncio.run(w._heartbeat("j1"))
    assert "j1" not in w._running


def test_worker_heartbeat_discards_other_owner() -> None:
    repo = FakeRepo()
    w = _worker(repo, FakeEngine())
    job = _job(state=JobState.leased, owner="w2")
    repo.jobs["j1"] = job
    w._running.add("j1")
    asyncio.run(w._heartbeat("j1"))
    assert "j1" not in w._running


def test_worker_heartbeat_saves_when_owned() -> None:
    repo = FakeRepo()
    w = _worker(repo, FakeEngine())
    job = _job(state=JobState.leased, owner="w1")
    repo.jobs["j1"] = job
    w._running.add("j1")
    asyncio.run(w._heartbeat("j1"))
    assert repo.renewed == ["j1"]
    assert job.heartbeat_at is not None
    assert job.lease_expires_at is not None
    assert "j1" in w._running


def test_worker_heartbeat_missing_job_discards() -> None:
    repo = FakeRepo()
    w = _worker(repo, FakeEngine())
    w._running.add("nope")
    asyncio.run(w._heartbeat("nope"))
    assert "nope" not in w._running
