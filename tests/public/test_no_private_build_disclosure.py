"""Regression tests: no private build disclosure in public surface."""

import pytest


@pytest.mark.skip(reason="Public surface audit not yet integrated")
class TestNoPrivateBuildDisclosure:
    """Public surface must not contain private build process."""

    async def test_no_claude_code_in_docs(self):
        """Public docs must not mention Claude Code as build tool."""
        pytest.fail("Public surface audit not yet integrated")

    async def test_no_private_model_id(self):
        pytest.fail("Public surface audit not yet integrated")

    async def test_no_local_paths(self):
        pytest.fail("Public surface audit not yet integrated")
