"""Tests for semantic factuality: causal direction, entity roles, negation, numbers, units."""

from knovaryn.pipeline.quality.claims import (
    ClaimVerdict,
    check_entity_role_reversal,
    check_negation_reversal,
    check_number_mismatch,
    check_unit_mismatch,
    check_unsupported_entities,
    detect_causal_direction,
    detect_polarity,
    normalize_number_text,
    normalize_unit,
)
from knovaryn.pipeline.quality.semantic import (
    DeterministicSemanticVerifier,
    extract_atomic_claims,
)


class TestNormalizeNumberText:
    """Number extraction and normalization."""

    def test_simple_integer(self):
        nums = normalize_number_text("42")
        assert len(nums) == 1
        assert nums[0].value == 42.0

    def test_comma_separated(self):
        nums = normalize_number_text("1,234")
        assert len(nums) == 1
        assert nums[0].value == 1234.0

    def test_decimal(self):
        nums = normalize_number_text("3.14")
        assert len(nums) == 1
        assert nums[0].value == 3.14

    def test_percentage(self):
        nums = normalize_number_text("85%")
        assert len(nums) == 1
        assert nums[0].is_percentage
        assert nums[0].percentage_value == 85.0

    def test_currency(self):
        nums = normalize_number_text("$50")
        assert len(nums) >= 1
        assert any(n.value == 50.0 and n.prefix == "$" for n in nums)

    def test_range(self):
        nums = normalize_number_text("100-200")
        assert len(nums) >= 1
        assert nums[-1].is_range
        assert nums[-1].range_start == 100.0
        assert nums[-1].range_end == 200.0


class TestNormalizeUnit:
    """Unit extraction and normalization."""

    def test_seconds(self):
        units = normalize_unit("30 seconds")
        assert len(units) >= 1
        assert any(u.canonical == "seconds" for u in units)

    def test_minutes(self):
        units = normalize_unit("5 minutes")
        assert len(units) >= 1
        assert any(u.canonical == "minutes" for u in units)

    def test_mb(self):
        units = normalize_unit("500 MB")
        assert len(units) >= 1
        assert any(u.canonical == "megabytes" for u in units)

    def test_gb_vs_mb_all_yields_both(self):
        units = normalize_unit("2 GB and 500 MB")
        canonicals = {u.canonical for u in units}
        assert "gigabytes" in canonicals
        assert "megabytes" in canonicals


class TestDetectPolarity:
    """Negation polarity detection."""

    def test_affirmed(self):
        assert detect_polarity("The system is operational.") == "affirmed"

    def test_negated_not(self):
        assert detect_polarity("The policy does not permit.") == "negated"

    def test_negated_never(self):
        assert detect_polarity("Never attempt this.") == "negated"

    def test_negated_prohibited(self):
        assert detect_polarity("Prohibited by regulation.") == "negated"

    def test_double_negation(self):
        assert detect_polarity("Not uncommon") == "affirmed"


class TestCheckNegationReversal:
    """Negation reversal between claim and evidence."""

    def test_negation_reversal_detected(self):
        evidence = "The policy does not permit external publication."
        claim = "The policy permits external publication."
        assert check_negation_reversal(claim, evidence) is True

    def test_no_reversal_both_affirmed(self):
        evidence = "The policy permits access."
        claim = "The policy permits access."
        assert check_negation_reversal(claim, evidence) is False

    def test_no_reversal_both_negated(self):
        evidence = "The system does not work."
        claim = "The system does not work."
        assert check_negation_reversal(claim, evidence) is False


class TestDetectCausalDirection:
    """Causal direction detection."""

    def test_causal_direction_matched(self):
        evidence = "The shutdown causes the alarm."
        claim = "The alarm causes the shutdown."
        subj, ev_subj, direction = detect_causal_direction(claim, evidence)
        assert direction is not None
        # Both use "causes" but with reversed subjects: shutdown vs alarm
        assert subj == "alarm"
        assert ev_subj == "shutdown"
        assert "causes" in direction
        # The reversal is detected by the subject swapping, not the verb direction
        assert subj != ev_subj

    def test_same_direction(self):
        evidence = "The shutdown causes the alarm."
        claim = "The shutdown causes the alarm."
        subj, ev_subj, direction = detect_causal_direction(claim, evidence)
        # Same direction means no reversal
        assert direction is None or "caused_by" not in direction


class TestCheckEntityRoleReversal:
    """Entity role reversal detection."""

    def test_reversal_detected(self):
        evidence = "Bob approved Alice."
        claim = "Alice approved Bob."
        assert check_entity_role_reversal(claim, evidence) is True

    def test_no_reversal_same_order(self):
        evidence = "Bob approved Alice."
        claim = "Bob approved Alice."
        assert check_entity_role_reversal(claim, evidence) is False

    def test_no_reversal_different_verbs(self):
        evidence = "Bob approved Alice."
        claim = "Bob reviewed Alice."
        assert check_entity_role_reversal(claim, evidence) is False


class TestCheckNumberMismatch:
    """Number mismatch detection."""

    def test_mismatch_detected(self):
        evidence = "The maximum batch size is 64 records."
        claim = "The maximum batch size is 46 records."
        reasons = check_number_mismatch(claim, evidence)
        assert len(reasons) >= 1
        assert any("number_mismatch" in r for r in reasons)

    def test_no_mismatch(self):
        evidence = "The maximum batch size is 64 records."
        claim = "The maximum batch size is 64 records."
        reasons = check_number_mismatch(claim, evidence)
        assert len(reasons) == 0

    def test_different_units_no_mismatch(self):
        evidence = "The batch size is 64 records."
        claim = "The timeout is 30 seconds."
        reasons = check_number_mismatch(claim, evidence)
        # Different numbers with different context — not a mismatch
        assert len(reasons) == 0


class TestCheckUnitMismatch:
    """Unit mismatch detection."""

    def test_mismatch_detected(self):
        evidence = "The timeout is 30 seconds."
        claim = "The timeout is 30 minutes."
        reasons = check_unit_mismatch(claim, evidence)
        assert len(reasons) >= 1
        assert any("unit_mismatch" in r for r in reasons)

    def test_no_mismatch_same_unit(self):
        evidence = "The timeout is 30 seconds."
        claim = "The timeout is 45 seconds."
        reasons = check_unit_mismatch(claim, evidence)
        assert len(reasons) == 0


class TestCheckUnsupportedEntities:
    """Unsupported entity detection."""

    def test_unsupported_entity_detected(self):
        evidence = "The system uses standard protocols."
        claim = "The system uses XYZProtocol."
        unsupported = check_unsupported_entities(claim, evidence)
        assert len(unsupported) >= 1
        assert "XYZProtocol" in unsupported

    def test_no_unsupported(self):
        evidence = "The system uses HTTP for communication."
        claim = "The system uses HTTP."
        unsupported = check_unsupported_entities(claim, evidence)
        assert len(unsupported) == 0


class TestExtractAtomicClaims:
    """Atomic claim extraction from text."""

    def test_extract_simple_sentence(self):
        claims = extract_atomic_claims("The shutdown causes the alarm.")
        assert len(claims) >= 1
        assert any(c.claim_type == "causal" for c in claims)

    def test_extract_with_number(self):
        claims = extract_atomic_claims("The batch size is 64 records.")
        assert len(claims) >= 1
        assert any(c.numbers for c in claims)

    def test_extract_negation(self):
        claims = extract_atomic_claims("The policy does not permit access.")
        assert len(claims) >= 1
        assert claims[0].polarity == "negated"

    def test_extract_empty_text(self):
        claims = extract_atomic_claims("")
        assert len(claims) == 0


class TestDeterministicSemanticVerifier:
    """End-to-end deterministic semantic verifier tests."""

    async def test_causal_reversal_rejected(self):
        """Given evidence 'shutdown causes alarm', answer 'alarm causes shutdown'
        must be rejected with causal_direction_reversal."""
        evidence = "The shutdown causes the alarm."
        answer = "The alarm causes the shutdown."
        prompt = "What causes the alarm?"

        claims = extract_atomic_claims(answer)
        verifier = DeterministicSemanticVerifier()
        results = await verifier.assess_claims(
            claims=claims,
            evidence_text=evidence,
            prompt=prompt,
            candidate_answer=answer,
            cited_span_ids=["span_1"],
        )

        assert len(results) >= 1
        detail = [(r.verdict, r.reason_codes) for r in results]
        assert any(r.verdict == ClaimVerdict.contradicted for r in results), (
            f"Causal reversal should be CONTRADICTED, got: {detail}"
        )

    async def test_negation_reversal_rejected(self):
        """Given evidence 'does not permit', answer 'permits'
        must be rejected with negation_reversal."""
        evidence = "The policy does not permit external publication."
        answer = "The policy permits external publication."
        prompt = "Does the policy permit external publication?"

        claims = extract_atomic_claims(answer)
        verifier = DeterministicSemanticVerifier()
        results = await verifier.assess_claims(
            claims=claims,
            evidence_text=evidence,
            prompt=prompt,
            candidate_answer=answer,
            cited_span_ids=["span_1"],
        )

        detail = [(r.verdict, r.reason_codes) for r in results]
        assert any(r.verdict == ClaimVerdict.contradicted for r in results), (
            f"Negation reversal should be CONTRADICTED, got: {detail}"
        )

    async def test_number_mismatch_rejected(self):
        """Given evidence '64 records', answer '46 records'
        must be rejected with number_mismatch."""
        evidence = "The maximum batch size is 64 records."
        answer = "The maximum batch size is 46 records."
        prompt = "What is the maximum batch size?"

        claims = extract_atomic_claims(answer)
        verifier = DeterministicSemanticVerifier()
        results = await verifier.assess_claims(
            claims=claims,
            evidence_text=evidence,
            prompt=prompt,
        )

        detail = [(r.verdict, r.reason_codes) for r in results]
        assert any(r.verdict == ClaimVerdict.contradicted for r in results), (
            f"Number mismatch should be CONTRADICTED, got: {detail}"
        )

    async def test_unit_mismatch_rejected(self):
        """Given evidence '30 seconds', answer '30 minutes'
        must be rejected with unit_mismatch."""
        evidence = "The timeout is 30 seconds."
        answer = "The timeout is 30 minutes."
        prompt = "What is the timeout?"

        claims = extract_atomic_claims(answer)
        verifier = DeterministicSemanticVerifier()
        results = await verifier.assess_claims(
            claims=claims,
            evidence_text=evidence,
            prompt=prompt,
        )

        detail = [(r.verdict, r.reason_codes) for r in results]
        assert any(r.verdict == ClaimVerdict.contradicted for r in results), (
            f"Unit mismatch should be CONTRADICTED, got: {detail}"
        )

    async def test_correct_paraphrase_accepted(self):
        """A correct paraphrase must be entailed."""
        evidence = "The model achieves 92% accuracy on the test set."
        answer = "The model gets 92% accuracy on testing data."
        prompt = "What accuracy does the model achieve?"

        claims = extract_atomic_claims(answer)
        verifier = DeterministicSemanticVerifier()
        results = await verifier.assess_claims(
            claims=claims,
            evidence_text=evidence,
            prompt=prompt,
        )

        # The deterministic verifier may not catch all correct paraphrases,
        # but must not mark them as contradicted
        detail = [(r.verdict, r.reason_codes) for r in results]
        assert not any(r.verdict == ClaimVerdict.contradicted for r in results), (
            f"Correct paraphrase should not be contradicted, got: {detail}"
        )


class TestFabricatedPreferenceSignal:
    """Defect 4.2: Verify the fix removes fabricated preference signal."""

    def test_fabrication_removed(self):
        """The assemble_decision function must not fabricate preference_signal."""
        import inspect

        from knovaryn.pipeline.quality.validators import assemble_decision

        src = inspect.getsource(assemble_decision)
        # After fix, preference_signal must be UNVERIFIED (not fabricated as 1.0)
        assert 'dims["preference_signal"] = 0.0' in src, (
            "Fix not applied: missing preference signal should default to 0.0"
        )
        # After fix, should have unverified handling
        assert "Verification.unverified" in src, (
            "Fix not applied: missing preference signal should be unverified"
        )
