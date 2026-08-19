"""Regression tests: cross-project provenance rejection."""

import pytest


@pytest.mark.skip(reason="Provenance gate not yet implemented")
class TestCrossProject:
    """Cross-project lineage must be rejected."""

    async def test_cross_project_source_rejected(self):
        pytest.fail("Provenance gate not yet implemented")
