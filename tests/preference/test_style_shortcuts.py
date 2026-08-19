"""Regression tests: style shortcut detection in preferences."""

import pytest


@pytest.mark.skip(reason="Preference validator not yet implemented")
class TestStyleShortcuts:
    """Style/length/verbosity must not be sole preference signals."""

    async def test_verbosity_without_value_detected(self):
        pytest.fail("Preference validator not yet implemented")
