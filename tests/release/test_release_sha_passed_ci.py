"""Regression tests: release SHA must pass CI."""

import pytest


@pytest.mark.skip(reason="Release governance not yet implemented")
class TestReleaseShaPassedCi:
    """Release target SHA must pass required checks."""

    async def test_release_sha_matches_tested_sha(self):
        pytest.fail("Release governance not yet implemented")
