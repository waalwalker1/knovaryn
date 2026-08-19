"""Regression tests: non-empty minimum provenance (defect 4.7)."""

import pytest


@pytest.mark.skip(reason="Provenance gate not yet implemented")
class TestNonemptyMinimum:
    """Export must be blocked on empty provenance arrays."""

    async def test_empty_source_document_ids_blocked(self):
        pytest.fail("Provenance gate not yet implemented")

    async def test_empty_source_span_ids_blocked(self):
        pytest.fail("Provenance gate not yet implemented")

    async def test_empty_generation_candidate_ids_blocked(self):
        pytest.fail("Provenance gate not yet implemented")
