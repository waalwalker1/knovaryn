"""Regression tests: version synchronization."""

import pytest


@pytest.mark.skip(reason="Version sync check not yet integrated")
class TestVersionSync:
    """Versions must be synchronized across the project."""

    async def test_pyproject_and_package_version_match(self):
        pytest.fail("Version sync check not yet implemented")

    async def test_no_stale_0_1_0_references(self):
        pytest.fail("Version sync check not yet implemented")
