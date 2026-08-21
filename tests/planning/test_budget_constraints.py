"""Regression tests: budget constraints in planner (defect 4.4).

Budget changes must affect the plan or stop generation when the cost/examples
ceiling is reached.
"""

from knovaryn.domain.schemas import DatasetPlan
from knovaryn.pipeline.planner import plan, top_up_plan


class TestBudgetConstraints:
    """Budget changes must affect plan or stop generation."""

    def _plan(self) -> DatasetPlan:
        return DatasetPlan(
            target_audience="test",
            task_family_proportions={"factual_explanation": 1.0},
            difficulty_distribution={"basic": 1.0},
        )

    def test_budget_changes_plan(self):
        """A restrictive budget yields a smaller plan than a generous one."""
        p = self._plan()
        r_strict = plan(p, chunk_count=10, target_examples=200, budget={"maximum_examples": 20})
        r_loose = plan(p, chunk_count=10, target_examples=200, budget={"maximum_examples": 200})
        assert r_strict.total_expected_examples < r_loose.total_expected_examples, (
            f"Strict budget ({r_strict.total_expected_examples}) should plan less than "
            f"loose budget ({r_loose.total_expected_examples})"
        )

    def test_hard_budget_stops_generation(self):
        """A budget that leaves no room returns a plan of zero or stops (no specs)."""
        p = self._plan()
        r = plan(p, chunk_count=10, target_examples=200, budget={"maximum_examples": 0})
        # With effectively no budget room, nothing is planned.
        assert r.total_expected_examples == 0, (
            f"Zero budget should plan nothing, got {r.total_expected_examples}"
        )

    def test_top_up_respects_budget(self):
        """A top-up that would exceed the budget is capped."""
        p = self._plan()
        base = plan(p, chunk_count=5, target_examples=100)
        # Budget allows only 50 more on top of the ~100 already planned.
        top = top_up_plan(
            base,
            target_examples=200,
            validated_examples=90,  # shortfall of 110
            budget={"maximum_examples": 120},
        )
        assert top.capped_by_budget is True, top.to_dict()
        assert top.additional <= 120, f"Top-up exceeded budget: {top.additional}"

    def test_top_up_fills_shortfall(self):
        """Top-up fills the validated shortfall to the target."""
        p = self._plan()
        base = plan(p, chunk_count=5, target_examples=100)
        top = top_up_plan(
            base,
            target_examples=100,
            validated_examples=70,  # shortfall of 30
        )
        assert top.shortfall == 30, top.to_dict()
        assert top.additional > 0, top.to_dict()
