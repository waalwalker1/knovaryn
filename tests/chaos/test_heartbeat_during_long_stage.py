"""Regression tests: heartbeat during long stage (defect 4.8)."""

import pytest


@pytest.mark.skip(reason="Durable pipeline not yet implemented")
class TestHeartbeatDuringLongStage:
    """Heartbeat must be renewed concurrently during long stages."""

    async def test_concurrent_heartbeat(self):
        pytest.fail("Durable pipeline not yet implemented")
