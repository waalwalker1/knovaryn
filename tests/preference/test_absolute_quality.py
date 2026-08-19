"""Regression tests: absolute quality floor for chosen/rejected."""

import pytest


@pytest.mark.skip(reason="Preference validator not yet implemented")
class TestAbsoluteQuality:
    """Chosen/rejected must meet absolute quality floors."""

    async def test_chosen_quality_floor(self):
        pytest.fail("Preference validator not yet implemented")
