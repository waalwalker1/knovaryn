"""Regression tests: package contents."""

import pytest


@pytest.mark.skip(reason="Package contents check not yet implemented")
class TestPackageContents:
    """Package must exclude private build material."""

    async def test_no_private_ledger_in_wheel(self):
        pytest.fail("Package contents check not yet implemented")

    async def test_no_private_ledger_in_sdist(self):
        pytest.fail("Package contents check not yet implemented")
