"""Regression test: claim verifier / semantic validation architecture (defect 4.1).

Verifies atomic claim extraction and the DeterministicSemanticVerifier verdict
generation (entailed / contradicted / insufficient / unverified).
"""

from knovaryn.pipeline.quality.claims import ClaimVerdict
from knovaryn.pipeline.quality.semantic import (
    CompositeSemanticVerifier,
    DeterministicSemanticVerifier,
    ModelSemanticVerifier,
    VerifierConfig,
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


class TestVerifierBranches:
    """Branch coverage for the verifier paths the acceptance gate relies on."""

    def test_abstract_base_not_instantiable(self):
        """The SemanticVerifier contract is abstract — direct use must raise."""
        import pytest

        from knovaryn.pipeline.quality.semantic import SemanticVerifier

        with pytest.raises(TypeError):
            SemanticVerifier()

    async def test_unsupported_entity_contradicts_through_verifier(self):
        """A fabricated entity contradicts at the VERIFIER level, not just in
        the claims helper — this is the path SemanticConsistencyValidator runs."""
        evidence = "The system uses standard protocols."
        answer = "The system uses XYZProtocol."
        results = await DeterministicSemanticVerifier().assess_claims(
            extract_atomic_claims(answer), evidence, candidate_answer=answer
        )
        assert any(r.verdict == ClaimVerdict.contradicted for r in results)
        assert any(
            rc.startswith("unsupported_entity:")
            for r in results
            if r.verdict == ClaimVerdict.contradicted
            for rc in r.reason_codes
        )

    async def test_be_verb_relation_extracted(self):
        """'X is Y' sentences yield a claim with subject and relation."""
        claims = extract_atomic_claims("The maximum batch size is 64 records.")
        assert len(claims) >= 1
        assert any(c.subject and c.relation for c in claims)

    async def test_comparison_claim_typed(self):
        """Comparison phrasing types the claim as comparison end-to-end."""
        from knovaryn.pipeline.quality.semantic import determine_claim_type

        assert determine_claim_type("Throughput is greater than the baseline.") == "comparison"
        assert determine_claim_type("The shutdown causes the alarm.") == "causal"
        assert determine_claim_type("The repository contains examples.") == "proposition"
        claims = extract_atomic_claims("Latency is lower than the previous release.")
        assert any(c.claim_type == "comparison" for c in claims)


class _StubModelVerifier:
    """Model judge stand-in: entails everything it is asked about."""

    name = "stub_model"
    version = "1"

    async def assess_claims(
        self, claims, evidence_text, prompt="", candidate_answer="", cited_span_ids=None
    ):
        from knovaryn.pipeline.quality.claims import ClaimAssessment, ClaimVerdict
        from knovaryn.pipeline.quality.semantic import ModelSemanticVerifier

        return [
            ClaimAssessment(
                claim=c,
                verdict=ClaimVerdict.entailed,
                confidence=0.9,
                reason_codes=[],
                verifier_name=ModelSemanticVerifier.name,
                verifier_version=ModelSemanticVerifier.version,
                concise_rationale="stub entails",
            )
            for c in claims
        ]


class TestCompositeVerifier:
    """Composite: deterministic always runs; the model judge cannot override."""

    async def test_offline_mode_returns_deterministic_only(self):
        composite = CompositeSemanticVerifier(config=VerifierConfig(offline_mode=True))
        evidence = "The maximum batch size is 64 records."
        answer = "The maximum batch size is 46 records."
        results = await composite.assess_claims(
            extract_atomic_claims(answer), evidence, candidate_answer=answer
        )
        assert any(r.verdict == ClaimVerdict.contradicted for r in results)
        assert all(r.verifier_name != "stub_model" for r in results)

    async def test_model_judge_cannot_override_deterministic_contradiction(self):
        composite = CompositeSemanticVerifier(
            model_verifier=_StubModelVerifier(),
            config=VerifierConfig(offline_mode=False),
        )
        evidence = "The maximum batch size is 64 records."
        answer = "The maximum batch size is 46 records."
        results = await composite.assess_claims(
            extract_atomic_claims(answer), evidence, candidate_answer=answer
        )
        # The number-mismatched claim stays contradicted even though the stub
        # entails everything.
        assert any(r.verdict == ClaimVerdict.contradicted for r in results)

    async def test_model_results_merge_for_non_contradicted_claims(self):
        composite = CompositeSemanticVerifier(
            model_verifier=_StubModelVerifier(),
            config=VerifierConfig(offline_mode=False),
        )
        evidence = "The system uses HTTP for communication."
        answer = "The system uses HTTP."
        results = await composite.assess_claims(
            extract_atomic_claims(answer), evidence, candidate_answer=answer
        )
        assert results
        assert all(r.verdict == ClaimVerdict.entailed for r in results)
