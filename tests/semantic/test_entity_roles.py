"""Regression test: entity-role reversal detection (defect 4.1).

Given evidence "Bob approved Alice", the answer "Alice approved Bob"
must be rejected with subject_object_reversal.
"""

from knovaryn.pipeline.quality.claims import ClaimVerdict
from knovaryn.pipeline.quality.semantic import (
    DeterministicSemanticVerifier,
    extract_atomic_claims,
)


class TestEntityRoles:
    """Entity-role reversal detection."""

    async def test_subject_object_reversal_rejected(self):
        """Evidence 'Bob approved Alice', answer 'Alice approved Bob' must be
        rejected with subject_object_reversal."""
        evidence = "Bob approved Alice."
        answer = "Alice approved Bob."
        claims = extract_atomic_claims(answer)
        verifier = DeterministicSemanticVerifier()
        results = await verifier.assess_claims(
            claims=claims,
            evidence_text=evidence,
            candidate_answer=answer,
        )
        assert len(results) >= 1
        assert any(r.verdict == ClaimVerdict.contradicted for r in results), (
            f"Entity role reversal should be CONTRADICTED, got: "
            f"{[(r.verdict, r.reason_codes) for r in results]}"
        )
        # The role reversal must carry a subject_object_reversal reason.
        assert any("subject_object_reversal" in r.reason_codes for r in results), (
            "Expected subject_object_reversal reason code"
        )
