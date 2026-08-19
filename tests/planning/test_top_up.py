"""Regression tests: top-up generation after validation (defect 4.4)."""

import pytest


@pytest.mark.skip(reason="Top-up not yet implemented")
class TestTopUp:
    """Top-up fills shortfalls after validation."""

    async def test_top_up_fills_shortfall(self):
        pytest.fail("Top-up not yet implemented")

    async def test_top_up_respects_budget(self):
        pytest.fail("Top-up not yet implemented")
