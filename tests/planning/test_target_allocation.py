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

    def test_default_spread_never_plans_zero_on_small_corpus(self):
        """Defect (v0.2.1 deployment E2E): the default 0.5/0.3/0.2 proportions
        spread across families × difficulties × topologies used to round EVERY
        cell to zero on a two-chunk document — the job then "succeeded" with an
        empty dataset. Largest-remainder apportionment must keep the planned
        total equal to the material available."""
        default = DatasetPlan()
        for chunks in (1, 2, 3, 5):
            r = plan(default, chunk_count=chunks)
            assert r.total_expected_examples == chunks, (
                f"chunk_count={chunks} planned {r.total_expected_examples} examples "
                f"(specs={[(s.topology, s.task_family, s.per_chunk) for s in r.specs]})"
            )
            assert r.specs, "a positive chunk count must yield at least one assignment spec"

    def test_target_driven_total_tracks_target(self):
        """The apportioned integer plan sums to the requested target."""
        p = DatasetPlan()
        for target in (1, 7, 10, 23):
            r = plan(p, chunk_count=50, target_examples=target)
            assert r.total_expected_examples == target, (
                f"target={target} planned {r.total_expected_examples}"
            )

    def test_empty_corpus_plans_nothing(self):
        """No parsed chunks → no specs (generation has nothing to ground in)."""
        r = plan(DatasetPlan(), chunk_count=0)
        assert r.total_expected_examples == 0 and not r.specs

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
