"""Regression tests: preference near-duplicate detection."""

import pytest


@pytest.mark.skip(reason="Preference validator not yet implemented")
class TestNearDuplicates:
    """Near-duplicate detection for preference pairs."""

    async def test_punctuation_only_difference_rejected(self):
        pytest.fail("Preference validator not yet implemented")

    async def test_semantic_near_duplicate_rejected(self):
        pytest.fail("Preference validator not yet implemented")
