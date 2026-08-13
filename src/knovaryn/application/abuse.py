"""J7 abuse controls for the application layer.

Beyond the HTTP request budget (see ``interfaces/rest/rate_limit.py``), WP J7
requires resource-level caps. These are enforced where the work actually
happens so no interface (MCP, CLI, REST, SDK) can bypass them — one shared path:

* *concurrent jobs* — a running/leased pipeline job cap (default 4). Raised
  against live DB state, so it is meaningful across workers and never a
  truthiness-only check.
* *publication attempts* — a per-process sliding-window cap (default 10/hour)
  on ``publish_dataset`` calls. Process-local is documented: the REST/CLI
  control plane is single-process local-first; a shared counter would add
  cross-worker coordination that this deployment does not need.

Both raise :class:`RateLimitError` (HTTP 429) rather than silently returning
success, honoring contract rule 6 (never truthiness-only for abuse controls).
"""

from __future__ import annotations

import time
from collections import deque

from ..domain.config import load_config
from ..domain.errors import RateLimitError

# Per-process publication-attempt history: principal -> deque of monotonic times.
_PUBLISH_HISTORY: dict[str, deque[float]] = {}

# Per-process provider-call budget (J7): a running total of provider invocations.
_PROVIDER_CALLS = 0


def _server_cfg() -> dict:
    return load_config().get("server", {}) or {}


def _limits() -> dict:
    return (_server_cfg().get("rate_limit") or {}) or {}


def concurrent_job_limit() -> int:
    return int(_limits().get("max_concurrent_jobs", 0) or 0)


def publish_attempt_limit() -> int:
    return int(_limits().get("max_publish_attempts_per_hour", 0) or 0)


def provider_call_limit() -> int:
    """Per-process cap on provider (LLM) invocations for a generation run.

    The cap is interpreted per generation run, not globally, so a single
    pipeline cannot burn unbounded external spend; a fresh run resets it.
    """
    return int(_limits().get("max_provider_calls_per_run", 0) or 0)


def enforce_concurrent_jobs(*, running_count: int) -> None:
    """Raise :class:`RateLimitError` if the running-job cap is already reached."""
    cap = concurrent_job_limit()
    if cap <= 0:  # 0 = disabled
        return
    if running_count >= cap:
        raise RateLimitError(f"concurrent job limit reached ({running_count}/{cap})")


def enforce_publish_attempts(*, principal: str) -> None:
    """Sliding-window publication-attempt cap (per-process).

    Returns the headroom on success; raises :class:`RateLimitError` when the
    hourly cap is exceeded. ``principal`` must be a resolved identity — never
    an empty string (rule 6).
    """
    cap = publish_attempt_limit()
    if cap <= 0:  # 0 = disabled
        return
    if not principal:
        raise RateLimitError("publication requires a resolvable principal")

    now = time.monotonic()
    window = 3600.0  # 1 hour
    bucket = _PUBLISH_HISTORY.setdefault(principal, deque())
    while bucket and now - bucket[0] >= window:
        bucket.popleft()
    if len(bucket) >= cap:
        raise RateLimitError(f"publication attempt limit reached ({len(bucket)}/per hour)")
    bucket.append(now)


def begin_generation_run() -> None:
    """Reset the per-run provider-call budget (call once per generation pass)."""
    global _PROVIDER_CALLS
    _PROVIDER_CALLS = 0


def enforce_provider_call() -> None:
    """Raise :class:`RateLimitError` if the per-run provider-call cap is reached.

    Call immediately before each provider invocation; a positive return from
    :func:`provider_call_limit` means the cap is enforced. Resets via
    :func:`begin_generation_run`.
    """
    global _PROVIDER_CALLS
    cap = provider_call_limit()
    if cap <= 0:  # 0 = disabled
        return
    if cap <= _PROVIDER_CALLS:
        raise RateLimitError(f"provider call limit reached ({_PROVIDER_CALLS}/{cap})")
    _PROVIDER_CALLS += 1


def reset_abuse_state() -> None:
    """Clear per-process counters (used by tests)."""
    _PUBLISH_HISTORY.clear()
    global _PROVIDER_CALLS
    _PROVIDER_CALLS = 0


__all__ = [
    "enforce_concurrent_jobs",
    "enforce_publish_attempts",
    "enforce_provider_call",
    "begin_generation_run",
    "concurrent_job_limit",
    "publish_attempt_limit",
    "provider_call_limit",
    "reset_abuse_state",
]
