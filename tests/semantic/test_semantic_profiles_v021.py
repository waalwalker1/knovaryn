"""Defect 3.8 (v0.2.1) — semantic validation profiles and the judge path.

Pins:
- profile registry: exactly offline-fast / certified-semantic; unknown names
  fail loudly;
- offline-fast performs no model calls and labels its limits;
- certified-semantic requires a judge-capable gateway at wiring time;
- the judge path produces typed, cited-evidence-only, claim-by-claim
  verdicts; deterministic contradictions are final; judge failure /
  invalid output / skipped claims all degrade to ``unverified``;
- no chain-of-thought is stored in assessments (short_rationale only);
- judge identity, prompt template and schema hash reach the gateway call.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from knovaryn.pipeline.quality.claims import ClaimVerdict
from knovaryn.pipeline.quality.profiles import (
    PROFILE_CERTIFIED_SEMANTIC,
    PROFILE_OFFLINE_FAST,
    SEMANTIC_PROFILES,
    build_semantic_verifier,
    spec_for,
)
from knovaryn.pipeline.quality.semantic import (
    ModelSemanticVerifier,
    VerifierConfig,
    extract_atomic_claims,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _RecordingGateway:
    """Minimal judge-capable gateway double: returns a canned JSON verdict."""

    verifier_model = "judge-x/7b"

    def __init__(self, payload: str, *, fail: bool = False):
        self.payload = payload
        self.fail = fail
        self.calls: list[dict] = []

    async def judge(
        self,
        *,
        system,
        user,
        prompt_template_version,
        schema_hash,
        stage="judge",
        max_output_tokens=None,
        model=None,
    ):
        self.calls.append(
            {
                "system": system,
                "user": user,
                "template": prompt_template_version,
                "schema_hash": schema_hash,
                "stage": stage,
            }
        )
        if self.fail:
            raise RuntimeError("provider down")
        return {"content": self.payload, "usage": {"input_tokens": 10, "output_tokens": 20}}


EVIDENCE = (
    "The XR-9 sensor is calibrated at the factory before shipping. "
    "Calibration takes 40 minutes per unit and must be repeated annually. "
    "Shipping crates hold up to 12 units."
)


class TestProfileRegistry:
    def test_exactly_two_profiles(self):
        assert sorted(SEMANTIC_PROFILES) == ["certified-semantic", "offline-fast"]

    def test_unknown_profile_rejected_everywhere(self):
        with pytest.raises(ValueError, match="unknown semantic profile"):
            spec_for("turbo")
        with pytest.raises(ValueError, match="unknown semantic profile"):
            build_semantic_verifier("turbo")

    def test_offline_fast_spec_is_network_free_and_honest(self):
        spec = spec_for(PROFILE_OFFLINE_FAST)
        assert spec.uses_model_judge is False
        assert spec.network_required is False
        assert "cannot prove entailment" in spec.limits or "paraphrases" in spec.limits

    def test_certified_spec_records_judge_and_fail_closed_limits(self):
        spec = spec_for(PROFILE_CERTIFIED_SEMANTIC)
        assert spec.uses_model_judge is True
        assert "unverified" in spec.limits

    def test_certified_without_gateway_is_wiring_error(self):
        with pytest.raises(ValueError, match="requires a model gateway"):
            build_semantic_verifier(PROFILE_CERTIFIED_SEMANTIC, gateway=None)

    def test_offline_fast_verifier_makes_no_model_calls(self):
        gw = _RecordingGateway("[]")
        verifier = build_semantic_verifier(PROFILE_OFFLINE_FAST, gateway=gw)
        claims = extract_atomic_claims("Calibration takes 40 minutes per unit.")
        results = _run(verifier.assess_claims(claims, EVIDENCE))
        assert results
        assert gw.calls == [], "offline-fast must never call the judge"
        assert all(
            r.verifier_name.startswith("deterministic")
            or "composite" in r.verifier_name
            or r.verifier_name
            for r in results
        )


class TestJudgePath:
    def _claims(self, text: str):
        return extract_atomic_claims(text)

    def test_structured_verdicts_parsed_and_cited_only(self):
        payload = json.dumps(
            [
                {
                    "claim_id": 0,
                    "verdict": "entailed",
                    "confidence": 0.97,
                    "evidence_span_ids": ["sp-a", "sp-fabricated"],
                    "reason_codes": [],
                },
            ]
        )
        gw = _RecordingGateway(payload)
        verifier = ModelSemanticVerifier(model_gateway=gw, model="judge-x/7b")
        claims = self._claims("Calibration takes 40 minutes per unit.")
        results = _run(
            verifier.assess_claims(
                claims,
                EVIDENCE,
                cited_span_ids=["sp-a", "sp-b"],
            )
        )
        assert len(results) == 1
        r = results[0]
        assert r.verdict is ClaimVerdict.entailed
        assert r.supporting_span_ids == ["sp-a"], "judge-invented spans must be dropped"
        assert r.verifier_name == "model_semantic:judge-x/7b:v2"

    def test_verdict_vocabulary_is_typed(self):
        payload = json.dumps(
            [
                {
                    "claim_id": 0,
                    "verdict": "contradicted",
                    "confidence": 0.9,
                    "evidence_span_ids": ["sp-a"],
                    "reason_codes": ["number_mismatch"],
                },
                {
                    "claim_id": 1,
                    "verdict": "insufficient_evidence",
                    "confidence": 0.5,
                    "evidence_span_ids": [],
                    "reason_codes": ["unsupported"],
                },
                {
                    "claim_id": 2,
                    "verdict": "unverified",
                    "confidence": 0.0,
                    "evidence_span_ids": [],
                    "reason_codes": [],
                },
            ]
        )
        verifier = ModelSemanticVerifier(model_gateway=_RecordingGateway(payload))
        claims = self._claims(
            "Calibration takes 40 minutes. Crates hold 30 units. The sensor is popular."
        )
        results = _run(verifier.assess_claims(claims, EVIDENCE, cited_span_ids=["sp-a"]))
        verdicts = {r.verdict for r in results}
        assert verdicts <= {
            ClaimVerdict.entailed,
            ClaimVerdict.contradicted,
            ClaimVerdict.insufficient,
            ClaimVerdict.unverified,
        }
        assert any(r.verdict is ClaimVerdict.contradicted for r in results)
        assert any(r.verdict is ClaimVerdict.insufficient for r in results)

    def test_confidence_clamped_and_missing_claims_unverified(self):
        payload = json.dumps(
            [
                {
                    "claim_id": 0,
                    "verdict": "entailed",
                    "confidence": 4.2,
                    "evidence_span_ids": ["sp-a"],
                    "reason_codes": [],
                },
                # claim 1 deliberately absent
            ]
        )
        verifier = ModelSemanticVerifier(model_gateway=_RecordingGateway(payload))
        claims = self._claims("Calibration takes 40 minutes. Crates hold 12 units.")
        results = _run(verifier.assess_claims(claims, EVIDENCE, cited_span_ids=["sp-a"]))
        assert len(results) == len(claims)
        first = results[0]
        assert 0.0 <= first.confidence <= 1.0 and first.confidence == 1.0
        skipped = [r for r in results if "judge_no_verdict" in r.reason_codes]
        assert skipped and all(r.verdict is ClaimVerdict.unverified for r in skipped)

    def test_judge_failure_degrades_to_unverified(self):
        verifier = ModelSemanticVerifier(model_gateway=_RecordingGateway("", fail=True))
        claims = self._claims("Calibration takes 40 minutes per unit.")
        results = _run(verifier.assess_claims(claims, EVIDENCE, cited_span_ids=["sp-a"]))
        assert all(r.verdict is ClaimVerdict.unverified for r in results)
        assert all("model_verifier_failed" in r.reason_codes for r in results)

    def test_invalid_json_output_degrades_to_unverified(self):
        verifier = ModelSemanticVerifier(
            model_gateway=_RecordingGateway("I think claim 0 is fine!")
        )
        claims = self._claims("Calibration takes 40 minutes per unit.")
        results = _run(verifier.assess_claims(claims, EVIDENCE, cited_span_ids=["sp-a"]))
        assert all(r.verdict is ClaimVerdict.unverified for r in results)

    def test_no_gateway_unverified_never_entailed(self):
        verifier = ModelSemanticVerifier(model_gateway=None)
        claims = self._claims("Calibration takes 40 minutes per unit.")
        results = _run(verifier.assess_claims(claims, EVIDENCE))
        assert results
        assert all(r.verdict is ClaimVerdict.unverified for r in results)

    def test_no_chain_of_thought_persisted(self):
        payload = json.dumps(
            [
                {
                    "claim_id": 0,
                    "verdict": "entailed",
                    "confidence": 0.9,
                    "evidence_span_ids": ["sp-a"],
                    "reason_codes": [],
                    "reasoning": "Let me think step by step about the calibration...",
                },
            ]
        )
        verifier = ModelSemanticVerifier(model_gateway=_RecordingGateway(payload))
        claims = self._claims("Calibration takes 40 minutes per unit.")
        results = _run(verifier.assess_claims(claims, EVIDENCE, cited_span_ids=["sp-a"]))
        blob = json.dumps([r.model_dump(mode="json") for r in results])
        assert "step by step" not in blob

    def test_gateway_receives_identity_template_and_schema(self):
        payload = json.dumps(
            [
                {
                    "claim_id": 0,
                    "verdict": "entailed",
                    "confidence": 0.9,
                    "evidence_span_ids": ["sp-a"],
                    "reason_codes": [],
                },
            ]
        )
        gw = _RecordingGateway(payload)
        verifier = ModelSemanticVerifier(model_gateway=gw, model="judge-x/7b")
        claims = self._claims("Calibration takes 40 minutes per unit.")
        _run(verifier.assess_claims(claims, EVIDENCE, cited_span_ids=["sp-a"]))
        call = gw.calls[0]
        assert call["template"] == ModelSemanticVerifier.PROMPT_TEMPLATE_VERSION
        assert call["schema_hash"]
        assert call["stage"] == "semantic_judge"
        assert "EVIDENCE" in call["user"] and "CLAIMS" in call["user"]
        assert "outside knowledge" in call["system"]

    def test_composite_certified_construction(self):
        gw = _RecordingGateway("[]")
        verifier = build_semantic_verifier(PROFILE_CERTIFIED_SEMANTIC, gateway=gw)
        assert isinstance(verifier, object)
        cfg: VerifierConfig = verifier._config  # type: ignore[attr-defined]
        assert cfg.require_deterministic_checks is True
        assert cfg.offline_mode is False


class TestCertifiedCompositeEndToEnd:
    def test_deterministic_contradiction_is_final(self):
        """A number mismatch caught deterministically survives the judge saying
        'entailed' — the model can never override a deterministic
        contradiction (defect 3.8 hard rule)."""
        payload = json.dumps(
            [
                {
                    "claim_id": 0,
                    "verdict": "entailed",
                    "confidence": 0.99,
                    "evidence_span_ids": ["sp-a"],
                    "reason_codes": [],
                },
            ]
        )
        gw = _RecordingGateway(payload)
        verifier = build_semantic_verifier(PROFILE_CERTIFIED_SEMANTIC, gateway=gw)
        evidence = "The maximum batch size is 64 records."
        answer = "The maximum batch size is 46 records."
        claims = extract_atomic_claims(answer)
        results = _run(verifier.assess_claims(claims, evidence, cited_span_ids=["sp-a"]))
        assert any(r.verdict is ClaimVerdict.contradicted for r in results), (
            f"deterministic contradiction was overridden: {[r.verdict for r in results]}"
        )
