"""Budget controls (spec §7.5).

Estimate costs before generation and enforce hard limits (cost, tokens, calls,
duration, examples, rate). A job must pause with budget_exhausted before
exceeding a hard limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...domain.errors import BudgetExceededError
from ...domain.schemas import JobState


@dataclass
class BudgetState:
    maximum_cost_usd: float = 50.0
    maximum_calls: int = 10000
    maximum_input_tokens: int | None = None
    maximum_output_tokens: int | None = None
    maximum_duration_s: int | None = None
    maximum_examples: int = 2500
    per_provider_rate: dict[str, float] = field(default_factory=dict)

    # live accumulators
    spent_cost_usd: float = 0.0
    calls_made: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    examples_produced: int = 0

    def check(self, *, dt_s: float = 0.0) -> None:
        if self.spent_cost_usd >= self.maximum_cost_usd:
            raise BudgetExceededError(
                "hard budget would be exceeded (cost)", details={"spent": self.spent_cost_usd, "max": self.maximum_cost_usd}
            )
        if self.calls_made >= self.maximum_calls:
            raise BudgetExceededError("hard budget would be exceeded (calls)")
        if self.examples_produced >= self.maximum_examples:
            raise BudgetExceededError("hard budget would be exceeded (examples)")
        if self.maximum_input_tokens is not None and self.input_tokens >= self.maximum_input_tokens:
            raise BudgetExceededError("hard budget would be exceeded (input tokens)")
        if self.maximum_output_tokens is not None and self.output_tokens >= self.maximum_output_tokens:
            raise BudgetExceededError("hard budget would be exceeded (output tokens)")
        if self.maximum_duration_s is not None and dt_s >= self.maximum_duration_s:
            raise BudgetExceededError("hard budget would be exceeded (duration)")

    def account_call(self, *, cost_usd: float, input_tokens: int = 0, output_tokens: int = 0, count: int = 1) -> None:
        self.spent_cost_usd += cost_usd
        self.calls_made += count
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

    def account_examples(self, n: int) -> None:
        self.examples_produced += n

    def as_dict(self) -> dict[str, Any]:
        return {
            "spent_cost_usd": self.spent_cost_usd,
            "calls_made": self.calls_made,
            "examples_produced": self.examples_produced,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "maximum_cost_usd": self.maximum_cost_usd,
            "state_on_exceed": JobState.paused.value,
        }


def estimate_job_cost(*, tokens_in: int, tokens_out: int, price_input_per_m: float, price_output_per_m: float, calls: int) -> float:
    """Deterministic cost estimate (input+output at given per-1M prices)."""
    input_cost = (tokens_in / 1_000_000) * price_input_per_m
    output_cost = (tokens_out / 1_000_000) * price_output_per_m
    return round((input_cost + output_cost) * calls, 6)
