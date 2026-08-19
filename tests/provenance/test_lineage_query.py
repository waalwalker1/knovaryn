"""Regression tests: lineage query completeness."""

import pytest


@pytest.mark.skip(reason="Lineage service not yet implemented")
class TestLineageQuery:
    """Lineage query must resolve example → document → artifact."""

    async def test_full_lineage_resolution(self):
        pytest.fail("Lineage query not yet implemented")
