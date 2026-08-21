"""Regression test: claim verifier / semantic validation architecture (defect 4.1).

Verifies atomic claim extraction and the DeterministicSemanticVerifier verdict
generation (entailed / contradicted / insufficient / unverified).
"""

from knovaryn.pipeline.quality.claims import ClaimVerdict
from knovaryn.pipeline.quality.semantic import (
    DeterministicSemanticVerifier,
    ModelSemanticVerifier,
    extract_atomic_claims,
)


class TestClaimVerifier:
    """Atomic claim extraction and verdict generation."""

    def test_claims_extracted_from_text(self):
        """Non-trivial sentences produce atomic claims."""
        claims = extract_atomic_claims("The shutdown causes the alarm system to activate.")
        assert len(claims) >= 1
        assert any(c.claim_type == "causal" for c in claims)

    async def test_claim_verdict_entailed(self):
        """A verifiable claim matching the evidence is entailed."""
        evidence = "The model achieves 92% accuracy on the test set."
        answer = "The model achieves 92% accuracy on the test set."
        claims = extract_atomic_claims(answer)
        verifier = DeterministicSemanticVerifier()
        results = await verifier.assess_claims(
            claims=claims, evidence_text=evidence, candidate_answer=answer
        )
        assert len(results) >= 1
        assert all(r.verdict != ClaimVerdict.contradicted for r in results)

    async def test_claim_verdict_contradicted(self):
        """A number mismatch yields contradicted."""
        evidence = "The maximum batch size is 64 records."
        answer = "The maximum batch size is 46 records."
        claims = extract_atomic_claims(answer)
        verifier = DeterministicSemanticVerifier()
        results = await verifier.assess_claims(
            claims=claims, evidence_text=evidence, candidate_answer=answer
        )
        assert len(results) >= 1
        assert any(r.verdict == ClaimVerdict.contradicted for r in results)

    async def test_claim_verdict_insufficient(self):
        """A failed/unavailable model judge yields unverified, never a confident
        verdict — absence of evidence is never certification (fail-closed)."""
        # ModelSemanticVerifier with no gateway raises and must fall back to
        # UNVERIFIED, not fabricate an entailed/contradicted verdict.
        claims = extract_atomic_claims("The batch size is 64 records.")
        verifier = ModelSemanticVerifier(model_gateway=None)
        results = await verifier.assess_claims(
            claims=claims, evidence_text="The batch size is 64 records."
        )
        assert len(results) >= 1
        assert all(r.verdict == ClaimVerdict.unverified for r in results), (
            f"Failed judge must leave claims unverified, got: {[r.verdict for r in results]}"
        )
        assert any("model_verifier_failed" in r.reason_codes for r in results)
