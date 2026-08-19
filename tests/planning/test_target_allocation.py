"""Regression tests: target allocation and planner (defect 4.4)."""

import pytest


@pytest.mark.skip(reason="Planner allocation not yet implemented")
class TestTargetAllocation:
    """Target count changes must affect plan allocation."""

    async def test_target_20_vs_200(self):
        """target_examples=20 and target_examples=200 must produce different plans."""
        pytest.fail("Planner allocation not yet implemented")

    async def test_unsupported_field_validation_error(self):
        """Unsupported field must return 422/validation error."""
        pytest.fail("Planner allocation not yet implemented")
