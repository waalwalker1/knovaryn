"""Regression tests: exact location/precision provenance (defect 4.6)."""

import pytest


@pytest.mark.skip(reason="Provenance gate not yet implemented")
class TestExactLocation:
    """Location precision must be truthful."""

    async def test_chunk_precision_not_exact_page(self):
        """Span with chunk precision must not claim exact page traceability."""
        pytest.fail("Provenance gate not yet implemented")

    async def test_bbox_preserved_where_available(self):
        pytest.fail("Provenance gate not yet implemented")
