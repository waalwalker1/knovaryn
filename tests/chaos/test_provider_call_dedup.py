"""Regression tests: provider call deduplication (defect 4.8)."""

import pytest


@pytest.mark.skip(reason="Durable pipeline not yet implemented")
class TestProviderCallDedup:
    """Logical provider calls must not be duplicated after crash."""

    async def test_no_duplicate_logical_call(self):
        pytest.fail("Durable pipeline not yet implemented")

    async def test_no_duplicate_cost_event(self):
        pytest.fail("Durable pipeline not yet implemented")
