"""Regression test: causal reversal detection (defect 4.1).

Given evidence "The shutdown causes the alarm", the answer "The alarm causes
the shutdown" must be rejected as CONTRADICTED with reason_code
causal_direction_reversal.

This test file asserts that the CURRENT (pre-fix) behavior is INCORRECT:
it expects acceptance. After the semantic verifier is implemented, these
tests must be updated to expect rejection.
"""

import pytest

from knovaryn.domain.schemas import (
    CanonicalMessage,
    QualityAssessment,
    QualityStatus,
    Topology,
    TrainingExample,
    Verification,
)


def _make_example(
    prompt_text: str,
    answer_text: str,
    evidence: str,
    span_id: str = "span_1",
) -> tuple[TrainingExample, dict[str, str]]:
    example = TrainingExample(
        id="test_causal_1",
        project_id="test_proj",
        dataset_plan_id="test_plan",
        topology=Topology.sft,
        source_document_ids=["doc1"],
        source_span_ids=[span_id],
        prompt_messages=[CanonicalMessage(role="user", content=prompt_text)],
        chosen_messages=[CanonicalMessage(role="assistant", content=answer_text)],
        rejected_messages=[],
        metadata={},
    )
    ctx = {span_id: evidence}
    return example, ctx


@pytest.mark.skip(reason="Semantic verifier not yet implemented — known failure")
class TestCausalDirectionReversal:
    """Reproduce defect 4.1: causal reversal accepted as valid."""

    EVIDENCE = "The shutdown causes the alarm."

    async def test_causal_reversal_rejected(self):
        """Answer "The alarm causes the shutdown" must be CONTRADICTED."""
        example, ctx = _make_example(
            "What causes the alarm?",
            "The alarm causes the shutdown.",
            self.EVIDENCE,
        )
        # TODO: replace with SemanticVerifier call after implementation
        # This test must FAIL (current behavior accepts)
        pytest.fail(
            "Semantic verifier not implemented — causal reversal is currently accepted. "
            "After implementation, this test must assert: verdict=CONTRADICTED, "
            "quality_status=rejected, reason_code includes causal_direction_reversal"
        )


@pytest.mark.skip(reason="Semantic verifier not yet implemented — known failure")
class TestEntityRoleReversal:
    """Reproduce defect 4.1: entity-role reversal accepted."""

    EVIDENCE = "Bob approved Alice."

    async def test_subject_object_reversal_rejected(self):
        """Answer "Alice approved Bob" must be rejected."""
        example, ctx = _make_example(
            "What happened?",
            "Alice approved Bob.",
            self.EVIDENCE,
        )
        pytest.fail(
            "Semantic verifier not implemented — entity-role reversal is currently accepted. "
            "After implementation: quality_status=rejected, "
            "reason_code includes subject_object_reversal"
        )


@pytest.mark.skip(reason="Semantic verifier not yet implemented — known failure")
class TestNegationReversal:
    """Reproduce defect 4.1: negation reversal accepted."""

    EVIDENCE = "The policy does not permit external publication."

    async def test_negation_reversal_rejected(self):
        """Answer "The policy permits external publication" must be CONTRADICTED."""
        example, ctx = _make_example(
            "Does the policy permit external publication?",
            "The policy permits external publication.",
            self.EVIDENCE,
        )
        pytest.fail(
            "Semantic verifier not implemented — negation reversal is currently accepted."
        )


@pytest.mark.skip(reason="Semantic verifier not yet implemented — known failure")
class TestNumericalMismatch:
    """Reproduce defect 4.1: wrong number accepted."""

    EVIDENCE = "The maximum batch size is 64 records."

    async def test_wrong_number_rejected(self):
        """Answer "The maximum batch size is 46 records" must be rejected."""
        example, ctx = _make_example(
            "What is the maximum batch size?",
            "The maximum batch size is 46 records.",
            self.EVIDENCE,
        )
        pytest.fail(
            "Semantic verifier not implemented — numerical mismatch is currently accepted."
        )


@pytest.mark.skip(reason="Semantic verifier not yet implemented — known failure")
class TestUnitMismatch:
    """Reproduce defect 4.1: unit mismatch accepted."""

    EVIDENCE = "The timeout is 30 seconds."

    async def test_wrong_unit_rejected(self):
        """Answer "The timeout is 30 minutes" must be rejected."""
        example, ctx = _make_example(
            "What is the timeout?",
            "The timeout is 30 minutes.",
            self.EVIDENCE,
        )
        pytest.fail(
            "Semantic verifier not implemented — unit mismatch is currently accepted."
        )


class TestCurrentBehaviorIsBroken:
    """These tests confirm the current (pre-fix) broken behavior.

    They PASS because the current code accepts causal reversals, entity swaps,
    negation reversals, wrong numbers, and wrong units. After the semantic
    verifier is implemented, these must be updated to expect rejection.
    """

    EVIDENCE = "The shutdown causes the alarm."

    async def test_causal_reversal_currently_accepted(self):
        """Current behavior: causal reversal is accepted — this MUST fail after fix."""
        example, ctx = _make_example(
            "What causes the alarm?",
            "The alarm causes the shutdown.",
            self.EVIDENCE,
        )
        # Current grounding validator uses lexical overlap, which accepts this
        # because the same words appear
        from knovaryn.pipeline.quality.validators import (
            GroundingValidator,
            ValidatorContext,
        )

        validator = GroundingValidator()
        vctx = ValidatorContext(source_texts=ctx)
        assessment = await validator.assess(example, vctx)
        # Currently passes because lexical overlap doesn't detect causal reversal
        assert assessment.status == QualityStatus.accepted, (
            "Pre-fix: causal reversal should be accepted (broken behavior). "
            f"Got {assessment.status}"
        )

    @pytest.mark.skip(reason="No semantic verifier yet")
    async def test_causal_reversal_rejected_after_fix(self):
        """After semantic verifier, causal reversal must be rejected."""
        # Replace with real verifier call in Phase 1
        raise NotImplementedError("Semantic verifier not implemented yet")
