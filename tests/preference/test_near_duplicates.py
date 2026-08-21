"""Regression tests: preference near-duplicate detection (defect 4.2/4.3).

Near-duplicate chosen/rejected pairs provide no preference signal and must be
rejected.
"""

from knovaryn.pipeline.quality.preference import (
    PreferenceVerdict,
    check_identical_pairs,
)


class TestNearDuplicates:
    """Near-duplicate detection for preference pairs."""

    def test_punctuation_only_difference_rejected(self):
        """Pair differing only by punctuation carries no signal."""
        result = check_identical_pairs("The answer is 42.", "The answer is 42!")
        assert result.verdict == PreferenceVerdict.invalid, result.rationale
        assert any("duplicate" in c for c in result.reason_codes), result.reason_codes

    def test_semantic_near_duplicate_rejected(self):
        """Pair with only cosmetic word changes must be rejected."""
        result = check_identical_pairs(
            "The system processes data in real time using streaming.",
            "The system processes data in realtime using streaming.",
        )
        assert result.verdict == PreferenceVerdict.invalid, result.rationale
        assert any("duplicate" in c for c in result.reason_codes), result.reason_codes
