"""Retry classification (spec §7.4).

Bounded exponential backoff with jitter. Retryable vs non-retryable errors.
Never retry a deterministic policy rejection.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from ...domain.errors import (
    BudgetExceededError,
    PolicyBlockError,
    ProviderError,
)
from ...domain.schemas import JobState


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_s: float = 1.0
    max_delay_s: float = 60.0
    multiplier: float = 2.0


def classify_failure(exc: BaseException) -> str:
    """Return a stable classification key (spec §7.4)."""
    if isinstance(exc, BudgetExceededError):
        return "budget_exhausted"
    if isinstance(exc, PolicyBlockError):
        return "policy_block"
    if isinstance(exc, ProviderError):
        return "provider" if exc.retryable else "provider_non_retryable"
    name = type(exc).__name__.lower()
    if "timeout" in name or "ratelimit" in name or "rate_limit" in name or "connection" in name:
        return "transient"
    return "worker_failure"


def is_retryable(exc: BaseException, *, max_attempts: int = 3, attempt: int = 0) -> bool:
    if isinstance(exc, (BudgetExceededError, PolicyBlockError)):
        return False
    if isinstance(exc, ProviderError):
        return exc.retryable and attempt < max_attempts
    key = classify_failure(exc)
    if key == "transient":
        return attempt < max_attempts
    if key in ("provider", "worker_failure"):
        return attempt < max_attempts
    return False


@dataclass(frozen=True)
class BackoffResult:
    delay_s: float
    retry_after: str | None = None


def backoff_delay(
    policy: RetryPolicy, attempt: int, *, retry_after_header: str | None = None
) -> BackoffResult:
    """Exponential backoff with full jitter (bounded)."""
    if retry_after_header:
        try:
            secs = max(0.1, float(retry_after_header))
            return BackoffResult(
                delay_s=min(secs, policy.max_delay_s), retry_after=retry_after_header
            )
        except (TypeError, ValueError):
            pass
    cap = policy.base_delay_s * (policy.multiplier ** max(attempt, 0))
    cap = min(cap, policy.max_delay_s)
    delay = random.uniform(0.0, cap)  # full jitter
    return BackoffResult(delay_s=delay)


def state_for_exc(exc: BaseException) -> JobState:
    if isinstance(exc, (BudgetExceededError, PolicyBlockError)):
        return JobState.paused
    return JobState.failed
