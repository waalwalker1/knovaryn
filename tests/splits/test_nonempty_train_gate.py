"""Regression tests: non-empty training split gate (defect 4.5)."""

import pytest


@pytest.mark.skip(reason="Split integrity not yet implemented")
class TestNonemptyTrainGate:
    """Normal training release requires non-empty train split."""

    async def test_nonempty_train_required(self):
        """Release must be blocked when train_count = 0."""
        pytest.fail("Split gate not yet implemented")

    async def test_small_corpus_allowance(self):
        """Small corpus policy must be explicit."""
        pytest.fail("Split gate not yet implemented")
