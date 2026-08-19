"""Regression tests: external cancellation (defect 4.8)."""

import pytest


@pytest.mark.skip(reason="Durable pipeline not yet implemented")
class TestExternalCancel:
    """External cancellation must have bounded latency."""

    async def test_cancellation_during_generation(self):
        pytest.fail("Durable pipeline not yet implemented")
