"""Regression test: numbers, units, and dates detection (defect 4.1)."""

import pytest


@pytest.mark.skip(reason="Semantic verifier not yet implemented")
class TestNumbersUnitsDates:
    """Number, unit, and date mismatch detection."""

    async def test_wrong_number_rejected(self):
        pytest.fail("Semantic verifier not yet implemented")

    async def test_wrong_unit_rejected(self):
        pytest.fail("Semantic verifier not yet implemented")

    async def test_wrong_date_rejected(self):
        pytest.fail("Semantic verifier not yet implemented")

    async def test_correct_number_accepted(self):
        pytest.fail("Semantic verifier not yet implemented")
