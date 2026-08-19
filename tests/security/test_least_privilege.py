"""Regression tests: least-privilege scopes (defect 4.10)."""

import pytest


@pytest.mark.skip(reason="Security module not yet implemented")
class TestLeastPrivilege:
    """Remote tokens must not receive admin/publish by default."""

    async def test_admin_denied_by_default(self):
        pytest.fail("Security module not yet implemented")

    async def test_publish_denied_by_default(self):
        pytest.fail("Security module not yet implemented")
