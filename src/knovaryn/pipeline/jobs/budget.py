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
    # WP D7 — per-model and per-stage sub-budgets (keyed by name)
    per_model_max_cost_usd: dict[str, float] = field(default_factory=dict)
    per_stage_max_cost_usd: dict[str, float] = field(default_factory=dict)

    # live accumulators
    spent_cost_usd: float = 0.0
    calls_made: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    examples_produced: int = 0
    model_spent_cost_usd: dict[str, float] = field(default_factory=dict)
    stage_spent_cost_usd: dict[str, float] = field(default_factory=dict)

    def check(
        self, *, dt_s: float = 0.0, model: str | None = None, stage: str | None = None
    ) -> None:
        if self.spent_cost_usd >= self.maximum_cost_usd:
            raise BudgetExceededError(
                "hard budget would be exceeded (cost)",
                details={"spent": self.spent_cost_usd, "max": self.maximum_cost_usd},
            )
        if self.calls_made >= self.maximum_calls:
            raise BudgetExceededError("hard budget would be exceeded (calls)")
        if self.examples_produced >= self.maximum_examples:
            raise BudgetExceededError("hard budget would be exceeded (examples)")
        if self.maximum_input_tokens is not None and self.input_tokens >= self.maximum_input_tokens:
            raise BudgetExceededError("hard budget would be exceeded (input tokens)")
        if (
            self.maximum_output_tokens is not None
            and self.output_tokens >= self.maximum_output_tokens
        ):
            raise BudgetExceededError("hard budget would be exceeded (output tokens)")
        if self.maximum_duration_s is not None and dt_s >= self.maximum_duration_s:
            raise BudgetExceededError("hard budget would be exceeded (duration)")
        if model is not None and self.per_model_max_cost_usd:
            cap = self.per_model_max_cost_usd.get(model)
            if cap is not None and self.model_spent_cost_usd.get(model, 0.0) >= cap:
                raise BudgetExceededError(
                    "hard budget would be exceeded (per-model cost)",
                    details={
                        "model": model,
                        "spent": self.model_spent_cost_usd.get(model, 0.0),
                        "max": cap,
                    },
                )
        if stage is not None and self.per_stage_max_cost_usd:
            cap = self.per_stage_max_cost_usd.get(stage)
            if cap is not None and self.stage_spent_cost_usd.get(stage, 0.0) >= cap:
                raise BudgetExceededError(
                    "hard budget would be exceeded (per-stage cost)",
                    details={
                        "stage": stage,
                        "spent": self.stage_spent_cost_usd.get(stage, 0.0),
                        "max": cap,
                    },
                )

    def account_call(
        self,
        *,
        cost_usd: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        count: int = 1,
        model: str | None = None,
        stage: str | None = None,
    ) -> None:
        self.spent_cost_usd += cost_usd
        self.calls_made += count
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        if model is not None:
            self.model_spent_cost_usd[model] = self.model_spent_cost_usd.get(model, 0.0) + cost_usd
        if stage is not None:
            self.stage_spent_cost_usd[stage] = self.stage_spent_cost_usd.get(stage, 0.0) + cost_usd

    def reconcile(self, **kw: Any) -> None:
        """Post-usage check so the call that crosses a hard limit pauses now.

        Called right after accounting for a call; raises BudgetExceededError as
        soon as a limit is crossed rather than waiting for the next pre-call check.
        """
        self.check(**kw)

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


def estimate_job_cost(
    *,
    tokens_in: int,
    tokens_out: int,
    price_input_per_m: float,
    price_output_per_m: float,
    calls: int,
) -> float:
    """Deterministic cost estimate (input+output at given per-1M prices)."""
    input_cost = (tokens_in / 1_000_000) * price_input_per_m
    output_cost = (tokens_out / 1_000_000) * price_output_per_m
    return round((input_cost + output_cost) * calls, 6)
