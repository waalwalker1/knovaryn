"""Regression tests: expired lease reclaim (defect 4.8)."""

import pytest


@pytest.mark.skip(reason="Durable pipeline not yet implemented")
class TestExpiredLeaseReclaim:
    """Expired running/leased jobs must be reclaimable."""

    async def test_expired_lease_reclaimed(self):
        pytest.fail("Durable pipeline not yet implemented")
