"""Regression tests: pairwise order consistency."""

import pytest


@pytest.mark.skip(reason="Preference validator not yet implemented")
class TestPairwiseOrder:
    """A/B order consistency for preference judgement."""

    async def test_order_consistency_required(self):
        pytest.fail("Preference validator not yet implemented")
