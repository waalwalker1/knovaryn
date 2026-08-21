"""Regression tests: target allocation and planner (defect 4.4).

Target count changes must affect plan allocation, and unsupported plan fields
must raise a validation error.
"""

import pytest

from knovaryn.domain.schemas import DatasetPlan
from knovaryn.pipeline.planner import plan


class TestTargetAllocation:
    """Target count changes must affect plan allocation."""

    def _plan(self) -> DatasetPlan:
        return DatasetPlan(
            target_audience="test",
            task_family_proportions={"factual_explanation": 1.0},
            difficulty_distribution={"basic": 1.0},
        )

    def test_target_20_vs_200(self):
        """target_examples=20 and target_examples=200 must produce different plans."""
        p = self._plan()
        r20 = plan(p, chunk_count=10, target_examples=20)
        r200 = plan(p, chunk_count=10, target_examples=200)
        # Per-chunk assignment for the same composition cell differs.
        specs20 = {s.topology: s.per_chunk for s in r20.specs}
        specs200 = {s.topology: s.per_chunk for s in r200.specs}
        assert specs20 != specs200, f"Targets 20 and 200 produced identical allocation: {specs20}"

    def test_target_greater_than_default(self):
        """A larger target yields a larger planned total than a smaller target."""
        p = self._plan()
        r_small = plan(p, chunk_count=10, target_examples=50)
        r_large = plan(p, chunk_count=10, target_examples=500)
        assert r_large.total_expected_examples > r_small.total_expected_examples, (
            f"Larger target should plan more: {r_small.total_expected_examples} vs "
            f"{r_large.total_expected_examples}"
        )

    def test_unsupported_field_validation_error(self):
        """Unsupported field must raise a validation/422 error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            DatasetPlan(
                target_audience="test",
                **{"totally_unknown_field": 123},  # type: ignore[arg-type]
            )

    def test_budget_caps_target(self):
        """A target above the budget maximum_examples is clamped down."""
        p = self._plan()
        r = plan(
            p,
            chunk_count=10,
            target_examples=1000,
            budget={"maximum_examples": 30},
        )
        assert r.total_expected_examples <= 30, (
            f"Budget cap not honored: planned {r.total_expected_examples} > 30"
        )
