"""Regression test: negation reversal detection (defect 4.1).

Given evidence "the policy does not permit", an answer that claims it "permits"
must be rejected with negation_reversal.
"""

from knovaryn.pipeline.quality.claims import ClaimVerdict
from knovaryn.pipeline.quality.semantic import (
    DeterministicSemanticVerifier,
    extract_atomic_claims,
)


class TestNegation:
    """Negation reversal detection."""

    async def test_negation_reversal_rejected(self):
        """Evidence 'does not permit', answer 'permits' must be rejected with
        negation_reversal."""
        evidence = "The policy does not permit external publication."
        answer = "The policy permits external publication."
        claims = extract_atomic_claims(answer)
        verifier = DeterministicSemanticVerifier()
        results = await verifier.assess_claims(
            claims=claims,
            evidence_text=evidence,
            candidate_answer=answer,
        )
        assert len(results) >= 1
        assert any(r.verdict == ClaimVerdict.contradicted for r in results), (
            f"Negation reversal should be CONTRADICTED, got: "
            f"{[(r.verdict, r.reason_codes) for r in results]}"
        )
        assert any("negation_reversal" in r.reason_codes for r in results), (
            "Expected negation_reversal reason code"
        )
