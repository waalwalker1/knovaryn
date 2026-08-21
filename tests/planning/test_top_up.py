"""Regression tests: top-up generation after validation (defect 4.4).

Top-up fills shortfalls after validation, within budget.
"""

from knovaryn.domain.schemas import DatasetPlan
from knovaryn.pipeline.planner import plan, top_up_plan


class TestTopUp:
    """Top-up fills shortfalls after validation."""

    def test_top_up_fills_shortfall(self):
        """After validation drops examples, top-up fills up to the target."""
        p = DatasetPlan(
            target_audience="test",
            task_family_proportions={"factual_explanation": 1.0},
            difficulty_distribution={"basic": 1.0},
        )
        base = plan(p, chunk_count=4, target_examples=80)
        top = top_up_plan(
            base,
            target_examples=80,
            validated_examples=50,  # 30 short
        )
        assert top.shortfall == 30, top.to_dict()
        assert top.additional == 30, top.to_dict()
        assert top.capped_by_budget is False, top.to_dict()

    def test_top_up_respects_budget(self):
        """Top-up declines to plan beyond the budget hard cap."""
        p = DatasetPlan(
            target_audience="test",
            task_family_proportions={"factual_explanation": 1.0},
            difficulty_distribution={"basic": 1.0},
        )
        base = plan(p, chunk_count=4, target_examples=80)
        top = top_up_plan(
            base,
            target_examples=200,
            validated_examples=50,
            budget={"maximum_examples": 70},  # already planned 80, so no room
        )
        assert top.additional == 0, top.to_dict()
        assert top.capped_by_budget is True, top.to_dict()

    def test_no_shortfall_no_topup(self):
        """When validation meets the target, no top-up is needed."""
        p = DatasetPlan(
            target_audience="test",
            task_family_proportions={"factual_explanation": 1.0},
            difficulty_distribution={"basic": 1.0},
        )
        base = plan(p, chunk_count=4, target_examples=80)
        top = top_up_plan(base, target_examples=80, validated_examples=80)
        assert top.shortfall == 0, top.to_dict()
        assert top.additional == 0, top.to_dict()
