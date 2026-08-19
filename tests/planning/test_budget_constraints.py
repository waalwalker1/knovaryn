"""Regression tests: budget constraints in planner (defect 4.4)."""

import pytest


@pytest.mark.skip(reason="Budget constraints not yet implemented")
class TestBudgetConstraints:
    """Budget changes must affect plan or stop generation."""

    async def test_budget_changes_plan(self):
        pytest.fail("Budget constraints not yet implemented")

    async def test_hard_budget_stops_generation(self):
        pytest.fail("Budget constraints not yet implemented")
