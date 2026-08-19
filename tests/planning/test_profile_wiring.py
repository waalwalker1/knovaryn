"""Regression tests: runtime profile wiring (defect 4.9)."""

import pytest


@pytest.mark.skip(reason="Profile wiring not yet implemented")
class TestProfileWiring:
    """Runtime profile must thread through CLI/MCP/REST/SDK."""

    async def test_profile_changes_model(self):
        pytest.fail("Profile wiring not yet implemented")

    async def test_no_silent_fake_fallback(self):
        pytest.fail("Profile wiring not yet implemented")
