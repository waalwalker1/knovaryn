"""Budget controls (spec §7.5) — hard-limit enforcement and cost estimation."""

from __future__ import annotations

import pytest

from knovaryn.domain.errors import BudgetExceededError
from knovaryn.pipeline.jobs.budget import BudgetState, estimate_job_cost


def test_budget_check_passes_when_under_limits() -> None:
    b = BudgetState()
    b.check()  # no exception


def test_budget_rejects_cost_exceeded() -> None:
    b = BudgetState(maximum_cost_usd=10.0, spent_cost_usd=10.0)
    with pytest.raises(BudgetExceededError):
        b.check()


def test_budget_rejects_calls_exceeded() -> None:
    b = BudgetState(maximum_calls=3, calls_made=3)
    with pytest.raises(BudgetExceededError):
        b.check()


def test_budget_rejects_examples_exceeded() -> None:
    b = BudgetState(maximum_examples=5, examples_produced=5)
    with pytest.raises(BudgetExceededError):
        b.check()


def test_budget_rejects_input_tokens() -> None:
    b = BudgetState(maximum_input_tokens=100, input_tokens=100)
    with pytest.raises(BudgetExceededError):
        b.check()


def test_budget_rejects_output_tokens() -> None:
    b = BudgetState(maximum_output_tokens=100, output_tokens=150)
    with pytest.raises(BudgetExceededError):
        b.check()


def test_budget_rejects_duration() -> None:
    b = BudgetState(maximum_duration_s=10)
    with pytest.raises(BudgetExceededError):
        b.check(dt_s=11)


def test_budget_allows_under_tokens_and_duration() -> None:
    b = BudgetState(maximum_input_tokens=100, maximum_output_tokens=100, maximum_duration_s=10)
    b.check(dt_s=5)  # no exception


def test_account_call_accumulates() -> None:
    b = BudgetState()
    b.account_call(cost_usd=0.5, input_tokens=10, output_tokens=5, count=2)
    assert b.spent_cost_usd == 0.5
    assert b.calls_made == 2
    assert b.input_tokens == 10
    assert b.output_tokens == 5


def test_account_examples() -> None:
    b = BudgetState()
    b.account_examples(3)
    assert b.examples_produced == 3


def test_as_dict_includes_state_on_exceed() -> None:
    b = BudgetState()
    d = b.as_dict()
    assert d["state_on_exceed"] == "paused"
    assert d["maximum_cost_usd"] == 50.0


def test_estimate_job_cost() -> None:
    cost = estimate_job_cost(
        tokens_in=1_000_000,
        tokens_out=1_000_000,
        price_input_per_m=1.0,
        price_output_per_m=2.0,
        calls=1,
    )
    assert cost == pytest.approx(3.0)


def test_estimate_job_cost_zero_tokens() -> None:
    cost = estimate_job_cost(
        tokens_in=0, tokens_out=0, price_input_per_m=1.0, price_output_per_m=2.0, calls=5
    )
    assert cost == 0.0
