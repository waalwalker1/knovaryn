"""Regression test: numbers, units, and dates detection (defect 4.1).

A wrong number, wrong unit, or wrong date in an answer must be rejected.
"""

from knovaryn.pipeline.quality.claims import ClaimVerdict
from knovaryn.pipeline.quality.semantic import (
    DeterministicSemanticVerifier,
    extract_atomic_claims,
)


class TestNumbersUnitsDates:
    """Number, unit, and date mismatch detection."""

    async def test_wrong_number_rejected(self):
        """Answer's number differing from evidence must be rejected."""
        evidence = "The maximum batch size is 64 records."
        answer = "The maximum batch size is 46 records."
        claims = extract_atomic_claims(answer)
        verifier = DeterministicSemanticVerifier()
        results = await verifier.assess_claims(
            claims=claims, evidence_text=evidence, candidate_answer=answer
        )
        assert any(r.verdict == ClaimVerdict.contradicted for r in results), (
            f"Number mismatch should be CONTRADICTED, got: "
            f"{[(r.verdict, r.reason_codes) for r in results]}"
        )

    async def test_wrong_unit_rejected(self):
        """Answer's unit differing from evidence must be rejected."""
        evidence = "The timeout is 30 seconds."
        answer = "The timeout is 30 minutes."
        claims = extract_atomic_claims(answer)
        verifier = DeterministicSemanticVerifier()
        results = await verifier.assess_claims(
            claims=claims, evidence_text=evidence, candidate_answer=answer
        )
        assert any(r.verdict == ClaimVerdict.contradicted for r in results), (
            f"Unit mismatch should be CONTRADICTED, got: "
            f"{[(r.verdict, r.reason_codes) for r in results]}"
        )

    async def test_wrong_date_rejected(self):
        """A date mismatch between claim and evidence must be detected."""
        evidence = "The policy was released on 2024-03-01 and updated in 2025."
        answer = "The policy was released on 2024-05-01."
        # The exact release date differs -> the numbers inside the dates differ.
        claims = extract_atomic_claims(answer)
        verifier = DeterministicSemanticVerifier()
        results = await verifier.assess_claims(
            claims=claims, evidence_text=evidence, candidate_answer=answer
        )
        # The date numbers (03 vs 05) diverge and must not both be entailed with
        # full confidence — at minimum a mismatch signal must fire.
        assert any(r.verdict == ClaimVerdict.contradicted for r in results) or any(
            "number_mismatch" in r.reason_codes for r in results
        ), f"Date mismatch not detected: {[(r.verdict, r.reason_codes) for r in results]}"

    async def test_correct_number_accepted(self):
        """A matching number must not be contradicted."""
        evidence = "The maximum batch size is 64 records."
        answer = "The maximum batch size is 64 records."
        claims = extract_atomic_claims(answer)
        verifier = DeterministicSemanticVerifier()
        results = await verifier.assess_claims(
            claims=claims, evidence_text=evidence, candidate_answer=answer
        )
        assert not any(r.verdict == ClaimVerdict.contradicted for r in results), (
            f"Correct number should not be contradicted, got: "
            f"{[(r.verdict, r.reason_codes) for r in results]}"
        )
