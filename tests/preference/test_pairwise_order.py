"""Regression tests: pairwise order consistency (defect 4.2/4.3).

The preference judge must not be fooled by presentation order — highly similar
responses where the preference would hinge solely on order must be flagged.
"""

from knovaryn.pipeline.quality.preference import (
    PreferenceVerdict,
    check_pairwise_order,
)


class TestPairwiseOrder:
    """A/B order consistency for preference judgement."""

    def test_order_consistency_required(self):
        """Distinct responses should not raise order concerns."""
        result = check_pairwise_order(
            "The correct answer involves three initialization steps.",
            "The system should be initialized carefully.",
            "Initialization involves three steps.",
        )
        assert result.verdict != PreferenceVerdict.invalid, result.rationale

    def test_inconsistent_order_rejected(self):
        """Highly similar responses are order-sensitive and must be flagged."""
        result = check_pairwise_order(
            "The system uses HTTP for communication.",
            "The system uses HTTP for communication.",
            "The system uses HTTP.",
        )
        assert result.verdict == PreferenceVerdict.review, result.rationale
        assert any("order" in c for c in result.reason_codes), result.reason_codes
