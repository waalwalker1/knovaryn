"""Tests for preference/DPO quality validation (Phase 2).

Covers:
- Identical/near-duplicate pair rejection (defect 4.2)
- A/B order consistency
- Absolute quality floor
- Style shortcuts (verbosity/formatting as sole preference signal)
- Both-wrong and both-correct detection
"""

from knovaryn.domain.schemas import CanonicalMessage, Topology, TrainingExample
from knovaryn.pipeline.quality.preference import (
    PreferenceVerdict,
    check_absolute_quality,
    check_both_correct,
    check_both_wrong,
    check_identical_pairs,
    check_pairwise_order,
    check_preference_signal,
    check_style_shortcuts,
)
from knovaryn.pipeline.quality.validators import (
    PreferenceValidator,
    ValidatorContext,
    assemble_decision,
)


def _pref_example(chosen: str, rejected: str, **kw) -> TrainingExample:
    return TrainingExample(
        id="ex1",
        project_id="p1",
        topology=Topology.preference,
        prompt_messages=[CanonicalMessage(role="user", content="Answer based on the evidence.")],
        chosen_messages=[CanonicalMessage(role="assistant", content=chosen)],
        rejected_messages=[CanonicalMessage(role="assistant", content=rejected)],
        source_span_ids=["s1"],
        **kw,
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
        assert any("near_duplicate" in c for c in result.reason_codes), result.reason_codes

    def test_whitespace_only_difference_rejected(self):
        """Pair differing only by whitespace must be rejected."""
        result = check_identical_pairs("Hello  world", "Hello world")
        assert result.verdict == PreferenceVerdict.invalid, result.rationale
        codes = result.reason_codes
        assert any("identical" in c or "near_duplicate" in c for c in codes), codes

    def test_different_pairs_accepted(self):
        """Pair with meaningful differences must be accepted."""
        result = check_identical_pairs(
            "The sky is blue because of Rayleigh scattering.",
            "The sky appears blue because of how light scatters.",
        )
        assert result.verdict == PreferenceVerdict.valid, result.rationale


class TestAbsoluteQuality:
    """Chosen must have minimum absolute quality."""

    def test_chosen_quality_floor_enforced(self):
        """Empty chosen response must be rejected."""
        result = check_absolute_quality("")
        assert result.verdict == PreferenceVerdict.invalid, result.rationale
        assert "chosen_empty" in result.reason_codes, result.reason_codes

    def test_chosen_too_short_rejected(self):
        """Very short chosen response must be rejected."""
        result = check_absolute_quality("Yes.")
        assert result.verdict == PreferenceVerdict.invalid, result.rationale
        assert any("chosen_too_short" in c for c in result.reason_codes), result.reason_codes

    def test_boilerplate_only_rejected(self):
        """Boilerplate-only chosen must be rejected."""
        result = check_absolute_quality("According to the provided material, the answer is clear.")
        assert result.verdict == PreferenceVerdict.invalid, result.rationale

    def test_meaningful_chosen_accepted(self):
        """Meaningful chosen must be accepted."""
        result = check_absolute_quality(
            "The system architecture uses a modular design with three main components."
        )
        assert result.verdict == PreferenceVerdict.valid, result.rationale


class TestNearDuplicates:
    """Near-duplicate pairs must be rejected."""

    def test_near_duplicate_rejected(self):
        """Pairs with only minor word changes must be rejected."""
        result = check_identical_pairs(
            "The quick brown fox jumps over the lazy dog near the river bank.",
            "The quick brown fox jumps over the lazy dog near the riverbank.",
        )
        assert result.verdict == PreferenceVerdict.invalid, result.rationale
        assert any("near_duplicate" in c for c in result.reason_codes), result.reason_codes


class TestPairwiseOrder:
    """A/B order consistency."""

    def test_order_consistency_required(self):
        """Sufficiently different responses should not raise order concerns."""
        result = check_pairwise_order(
            "The correct answer involves three steps: first, initialize the system.",
            "The system should be initialized carefully before any operations.",
            "Initialization involves three steps.",
        )
        # Different enough — order shouldn't matter
        assert result.verdict != PreferenceVerdict.invalid, result.rationale

    def test_inconsistent_order_rejected(self):
        """Highly similar responses should raise order concerns."""
        result = check_pairwise_order(
            "The system uses HTTP for communication.",
            "The system uses HTTP for communication.",
            "The system uses HTTP.",
        )
        assert result.verdict == PreferenceVerdict.review, result.rationale
        assert any("order_sensitive" in c for c in result.reason_codes), result.reason_codes


class TestBothWrong:
    """Both responses factually wrong must be rejected."""

    def test_both_wrong_rejected(self):
        """Both chosen and rejected diverge entirely from the evidence."""
        result = check_both_wrong(
            "The Gemini protocol authenticates via TLS client certificates on port 1965.",
            "The SMB protocol uses proprietary token exchange on port 7100.",
            "The system uses OAuth2 bearer tokens over HTTPS for authentication.",
        )
        assert result.verdict == PreferenceVerdict.invalid, result.rationale
        assert any("both_wrong" in c for c in result.reason_codes), result.reason_codes


class TestBothCorrect:
    """Both factually correct with different phrasing — no clear preference."""

    def test_both_correct_rejected(self):
        result = check_both_correct(
            "The sky is blue due to Rayleigh scattering of sunlight.",
            "Rayleigh scattering causes the sky to appear blue during daytime.",
            "The sky appears blue because of Rayleigh scattering of shorter wavelengths.",
        )
        assert result.verdict == PreferenceVerdict.invalid, result.rationale
        assert any("both_correct" in c for c in result.reason_codes), result.reason_codes


class TestStyleShortcuts:
    """Style/length/verbosity must not be sole preference signal."""

    def test_chosen_verbosity_not_preference(self):
        """Chosen much longer but content-similar must be flagged."""
        result = check_style_shortcuts(
            "Based on the provided material, it appears that the system uses HTTP for "
            "communication purposes between the various components. The documentation "
            "suggests this is the preferred method for all internal communications "
            "within the architecture.",
            "The system uses HTTP.",
        )
        assert result.verdict == PreferenceVerdict.review, result.rationale
        assert any("verbosity_preference" in c for c in result.reason_codes), result.reason_codes

    def test_rejected_shorter_not_reason(self):
        """Short rejected + long chosen with similar content = style flag."""
        result = check_style_shortcuts(
            "The document says the system uses HTTP for all communications between components. "
            "This is clearly stated in section 3 of the architecture document.",
            "System uses HTTP for communications.",
        )
        assert result.verdict == PreferenceVerdict.review, result.rationale

    def test_chosen_worse_but_prettier_rejected(self):
        """This case is handled by both-correct/both-wrong checks."""
        result = check_style_shortcuts(
            "The system uses HTTP for all communications as documented.",
            "System uses HTTP as documented.",
        )
        assert result.verdict == PreferenceVerdict.valid, result.rationale


class TestPreferenceSignal:
    """Top-level preference signal check."""

    def test_identical_pairs_flagged(self):
        result = check_preference_signal("Same text here", "Same text here")
        assert result.verdict == PreferenceVerdict.invalid, result.rationale
        assert "identical_pair" in result.reason_codes, result.reason_codes

    def test_missing_rejected_flagged(self):
        result = check_preference_signal("Some chosen text", None)
        assert result.verdict == PreferenceVerdict.invalid, result.rationale

    def test_valid_pair_accepted(self):
        result = check_preference_signal(
            "The correct answer involves three initialization steps.",
            "Initialize the system carefully before operations.",
            "Initialization involves three steps.",
        )
        assert result.verdict == PreferenceVerdict.valid, result.rationale

    def test_style_shortcut_triggers_review(self):
        result = check_preference_signal(
            "Based on the provided material, it appears that the system uses HTTP for "
            "communication purposes between the various components. The documentation "
            "clearly suggests this.",
            "System uses HTTP.",
            "The system uses HTTP for communication.",
        )
        assert result.verdict == PreferenceVerdict.review, result.rationale

    def test_empty_chosen_invalid(self):
        result = check_preference_signal("", "Some rejected text")
        assert result.verdict == PreferenceVerdict.invalid, result.rationale


class TestPreferenceValidatorIntegration:
    """PreferenceValidator produces the preference_signal dimension."""

    async def test_identical_pair_rejected(self):
        ex = _pref_example("The answer is 42.", "The answer is 42.")
        v = PreferenceValidator()
        result = await v.assess(ex, ValidatorContext(source_texts={"s1": "The answer is 42."}))
        assert result.score < 0.8, f"Identical pair should be low quality, got {result.score}"
        assert any("no_preference_signal" in r for r in result.reason_codes), result.reason_codes

    async def test_genuine_pair_accepted(self):
        # Genuine pair: comparable length/format, but the chosen is factually
        # correct while the rejected carries a subtle factual error.
        ex = _pref_example(
            "The maximum batch size is 64 records as configured in the service.",
            "The maximum batch size is 46 records per the service configuration.",
        )
        v = PreferenceValidator()
        source = {"s1": "The maximum batch size is 64 records."}
        result = await v.assess(ex, ValidatorContext(source_texts=source))
        assert result.score >= 0.8, (
            f"Genuine pair should be high quality, got {result.score}: {result.reason_codes}"
        )

    async def test_style_only_pair_flagged(self):
        ex = _pref_example(
            "Based on the provided material, the system uses HTTP for communication purposes "
            "between the various components as documented. This is clearly stated.",
            "The system uses HTTP.",
        )
        v = PreferenceValidator()
        result = await v.assess(ex, ValidatorContext(source_texts={"s1": "The system uses HTTP."}))
        assert result.score < 0.8, (
            f"Style-only pair should be flagged, got {result.score}: {result.reason_codes}"
        )

    async def test_non_preference_topology_unverified(self):
        from knovaryn.domain.schemas import Topology as T

        ex = TrainingExample(
            id="ex2",
            project_id="p1",
            topology=T.sft,
            prompt_messages=[CanonicalMessage(role="user", content="Q")],
            chosen_messages=[CanonicalMessage(role="assistant", content="A")],
            source_span_ids=["s1"],
        )
        v = PreferenceValidator()
        result = await v.assess(ex, ValidatorContext(source_texts={"s1": "evidence"}))
        from knovaryn.domain.schemas import Verification

        assert result.verify_state == Verification.unverified, result.verify_state


class TestAssembleDecisionPreferenceFailClosed:
    """assemble_decision is fail-closed for missing preference_signal."""

    def test_missing_signal_not_fabricated(self):
        import inspect

        src = inspect.getsource(assemble_decision)
        # The buggy fabrication is entirely gone (not even as a comment).
        assert 'preference_signal"] = 1.0' not in src
        assert 'preference_signal"] = 0.0' in src
        assert "Verification.unverified" in src
