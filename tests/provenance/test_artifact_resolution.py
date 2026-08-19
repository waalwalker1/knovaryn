"""Regression tests: artifact resolution in provenance."""

import pytest


@pytest.mark.skip(reason="Provenance gate not yet implemented")
class TestArtifactResolution:
    """Original/canonical artifacts must exist and hashes match."""

    async def test_artifact_hash_match(self):
        pytest.fail("Provenance gate not yet implemented")
