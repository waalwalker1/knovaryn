"""Regression tests: preference/DPO validation (defects 4.2, 4.3).

Reproduce and verify fixes for:
- Identical chosen and rejected accepted (fabricated preference signal)
- Near-duplicate pairs accepted
- Chosen factually worse but stylistically better accepted
- Missing preference signal fabricated as 1.0
- A/B order inconsistency
"""

import inspect

from knovaryn.pipeline.quality.preference import (
    PreferenceVerdict,
    check_absolute_quality,
    check_both_correct,
    check_both_wrong,
    check_identical_pairs,
    check_pairwise_order,
    check_style_shortcuts,
)


class TestFabricatedPreferenceSignal:
    """Defect 4.2: missing preference signal fabricated as 1.0 and verified.

    FIX VERIFIED: assemble_decision must NOT fabricate a verified 1.0 for a
    missing preference signal — it must default to 0.0/unverified (fail-closed).
    """

    def test_fabrication_removed(self):
        from knovaryn.pipeline.quality.validators import assemble_decision

        src = inspect.getsource(assemble_decision)
        # The buggy fabrication (verified 1.0) must be gone...
        assert "preference_signal" in src
        assert 'dims["preference_signal"] = 1.0' not in src, (
            "Bug still present: missing preference signal is fabricated as 1.0"
        )
        # ...and replaced with fail-closed unverified.
        assert 'dims["preference_signal"] = 0.0' in src, (
            "Fix not applied: missing preference signal should default to 0.0"
        )
        assert "Verification.unverified" in src, (
            "Fix not applied: missing preference signal must be unverified"
        )


class TestIdenticalPairs:
    """Identical chosen/rejected must be rejected."""

    def test_identical_rejected(self):
        """Pair where chosen == rejected must be rejected."""
        result = check_identical_pairs("The answer is 42.", "The answer is 42.")
        assert result.verdict == PreferenceVerdict.invalid, result.rationale
        assert "identical_pair" in result.reason_codes, result.reason_codes

    def test_punctuation_only_difference_rejected(self):
        """Pair differing only by punctuation must be rejected."""
        result = check_identical_pairs("Hello world.", "Hello world!")
        assert result.verdict == PreferenceVerdict.invalid, result.rationale

    def test_whitespace_only_difference_rejected(self):
        """Pair differing only by whitespace must be rejected."""
        result = check_identical_pairs("Hello  world", "Hello world")
        assert result.verdict == PreferenceVerdict.invalid, result.rationale


class TestNearDuplicates:
    """Near-duplicate pairs must be rejected."""

    def test_near_duplicate_rejected(self):
        result = check_identical_pairs(
            "The quick brown fox jumps over the lazy dog near the river bank.",
            "The quick brown fox jumps over the lazy dog near the riverbank.",
        )
        assert result.verdict == PreferenceVerdict.invalid, result.rationale
        assert any("duplicate" in c for c in result.reason_codes), result.reason_codes


class TestPairwiseOrder:
    """A/B order consistency."""

    def test_order_consistency_required(self):
        result = check_pairwise_order(
            "The answer involves three initialization steps.",
            "Initialization should happen carefully.",
            "Initialization involves three steps.",
        )
        assert result.verdict != PreferenceVerdict.invalid, result.rationale

    def test_inconsistent_order_rejected(self):
        result = check_pairwise_order(
            "The system uses HTTP for communication.",
            "The system uses HTTP for communication.",
            "The system uses HTTP.",
        )
        assert result.verdict == PreferenceVerdict.review, result.rationale


class TestAbsoluteQuality:
    """Chosen must have minimum absolute quality."""

    def test_chosen_quality_floor_enforced(self):
        result = check_absolute_quality("")
        assert result.verdict == PreferenceVerdict.invalid, result.rationale

    def test_both_wrong_rejected(self):
        result = check_both_wrong(
            "The Gemini protocol uses TLS client certificates on port 1965.",
            "The SMB protocol uses token exchange on port 7100.",
            "The system uses OAuth2 bearer tokens over HTTPS.",
        )
        assert result.verdict == PreferenceVerdict.invalid, result.rationale

    def test_both_correct_rejected(self):
        result = check_both_correct(
            "Thermal runaway is prevented by built-in temperature sensors.",
            "Built-in temperature sensors stop thermal runaway.",
            "The battery has sensors to prevent thermal runaway by monitoring heat.",
        )
        assert result.verdict == PreferenceVerdict.invalid, result.rationale


class TestStyleShortcuts:
    """Style/length/verbosity must not be sole preference signal."""

    def test_chosen_verbosity_not_preference(self):
        result = check_style_shortcuts(
            "Based on the provided material, the system uses HTTP for communications "
            "between components as documented in the architecture. This is clear.",
            "The system uses HTTP.",
        )
        assert result.verdict == PreferenceVerdict.review, result.rationale

    def test_rejected_shorter_not_reason(self):
        result = check_style_shortcuts(
            "The document states the system uses HTTP for all component communications.",
            "System uses HTTP.",
        )
        assert result.verdict == PreferenceVerdict.review, result.rationale
