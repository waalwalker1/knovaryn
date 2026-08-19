"""Regression tests: non-loopback MCP refusal."""

import pytest


@pytest.mark.skip(reason="MCP security not yet implemented")
class TestNonloopbackRefusal:
    """Non-loopback MCP bind must require authentication."""

    async def test_remote_bind_refused_without_auth(self):
        pytest.fail("MCP security not yet implemented")
