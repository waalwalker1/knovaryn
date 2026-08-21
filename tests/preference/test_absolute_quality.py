"""Regression tests: absolute quality floor for chosen/rejected (defect 4.2).

The chosen response must carry a minimum absolute quality — an empty or
boilerplate-only chosen must never produce a preference signal.
"""

from knovaryn.pipeline.quality.preference import (
    PreferenceVerdict,
    check_absolute_quality,
)


class TestAbsoluteQuality:
    """Chosen/rejected must meet absolute quality floors."""

    def test_chosen_quality_floor(self):
        """Empty or trivial chosen responses are rejected."""
        empty = check_absolute_quality("")
        assert empty.verdict == PreferenceVerdict.invalid, empty.rationale

        boilerplate = check_absolute_quality(
            "According to the provided material, the answer is as stated."
        )
        assert boilerplate.verdict == PreferenceVerdict.invalid, boilerplate.rationale
