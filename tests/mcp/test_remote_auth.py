"""Regression tests: remote MCP authentication."""

import pytest


@pytest.mark.skip(reason="MCP security not yet implemented")
class TestRemoteAuth:
    """Streamable HTTP MCP must be authenticated."""

    async def test_missing_token_rejected(self):
        pytest.fail("MCP security not yet implemented")

    async def test_wrong_token_rejected(self):
        pytest.fail("MCP security not yet implemented")

    async def test_nonloopback_refused_without_token(self):
        pytest.fail("MCP security not yet implemented")
