"""Regression tests: small corpus policy (defect 4.5)."""

import pytest


@pytest.mark.skip(reason="Split integrity not yet implemented")
class TestSmallCorpusPolicy:
    """Small corpus rules for splits."""

    async def test_single_group_train_only(self):
        """1 source group produces train-only experimental release."""
        pytest.fail("Split integrity not yet implemented")

    async def test_two_groups_train_validation(self):
        """2 source groups produce train + validation, no test."""
        pytest.fail("Split integrity not yet implemented")

    async def test_three_groups_train_val_test(self):
        """3+ source groups produce train + val + test."""
        pytest.fail("Split integrity not yet implemented")
