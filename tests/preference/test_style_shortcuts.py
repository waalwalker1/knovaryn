"""Regression tests: style shortcut detection in preferences (defect 4.3).

Verbosity, length, or formatting must never be the sole preference signal.
"""

from knovaryn.pipeline.quality.preference import (
    PreferenceVerdict,
    check_style_shortcuts,
)


class TestStyleShortcuts:
    """Style/length/verbosity must not be sole preference signals."""

    def test_verbosity_without_value_detected(self):
        """Chosen that merely elaborates the rejected is a verbosity shortcut."""
        result = check_style_shortcuts(
            "Based on the provided material, it is evident that the system uses "
            "HTTP for all communication purposes between the various components. "
            "The documentation explicitly states this is the recommended method.",
            "The system uses HTTP.",
        )
        assert result.verdict == PreferenceVerdict.review, result.rationale
        assert any("verbosity" in c for c in result.reason_codes), result.reason_codes
