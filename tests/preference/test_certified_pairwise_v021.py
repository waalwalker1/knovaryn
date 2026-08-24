"""Defect 3.9 (v0.2.1) — certified pairwise preference judge.

Pins the full contract:
- both orders judged against the SAME cited evidence; A/B start randomized;
- order disagreement → review, never a clean pass;
- minimum preference margin enforced;
- length/style signature detection;
- chosen-win requires a real, classified rejected-side defect
  (style_only_difference does not count);
- both-good / both-bad / indistinguishable pairs never pass as preferences;
- judge identity + prompt template + schema hash recorded;
- NO judge executed → review/invalid with explicit reason — never an auto
  perfect preference signal.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from knovaryn.pipeline.quality.preference_judge import (
    CertifiedPairwiseJudge,
    PairwiseJudgement,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


EVIDENCE = (
    "The XR-9 sensor is calibrated at the factory before shipping. "
    "Calibration takes 40 minutes per unit and must be repeated annually."
)
PROMPT = "How long does calibration take and how often is it repeated?"
CHOSEN = "Calibration takes 40 minutes per unit and must be repeated annually."
REJECTED_BAD_NUMBER = "Calibration takes 15 minutes per unit and must be repeated monthly."


class _ScriptedGateway:
    """Returns per-call canned payloads in invocation order."""

    verifier_model = "pref-judge/1b"

    def __init__(self, payloads: list[str]):
        self.payloads = list(payloads)
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
        return {"content": self.payloads.pop(0)}


def _payload(
    first_q: float,
    second_q: float,
    preferred: str,
    defects_first=None,
    defects_second=None,
    confidence: float = 0.9,
) -> str:
    return json.dumps(
        {
            "first_quality": first_q,
            "second_quality": second_q,
            "preferred": preferred,
            "defects_first": defects_first or [],
            "defects_second": defects_second or [],
            "confidence": confidence,
        }
    )


class TestCertifiedPairwise:
    def _judge(self, gateway, **kw) -> CertifiedPairwiseJudge:
        return CertifiedPairwiseJudge(gateway, model="pref-judge/1b", **kw)

    def test_valid_pair_with_real_defect_and_consistent_orders(self):
        # run A: chosen FIRST (good=5 vs bad=2); run B: rejected first (2 vs 5)
        gw = _ScriptedGateway(
            [
                _payload(5, 2, "first", defects_second=["factually_incorrect_number_or_unit"]),
                _payload(2, 5, "second", defects_first=["factually_incorrect_number_or_unit"]),
            ]
        )
        j = self._judge(gw)
        out = _run(
            j.judge_pair(
                prompt=PROMPT,
                chosen_text=CHOSEN,
                rejected_text=REJECTED_BAD_NUMBER,
                evidence_text=EVIDENCE,
                force_chosen_first=True,
            )
        )
        assert isinstance(out, PairwiseJudgement)
        assert out.verdict == "valid"
        assert out.order_consistent is True
        assert out.preference_margin == 3.0
        assert out.rejected_defect_codes == ["factually_incorrect_number_or_unit"]
        assert out.judge_identity == "certified_pairwise:pref-judge/1b:v1"
        assert out.prompt_template_version == CertifiedPairwiseJudge.PROMPT_TEMPLATE_VERSION
        assert out.schema_hash
        assert 0.0 <= out.confidence <= 1.0

    def test_two_calls_made_with_reversed_order(self):
        gw = _ScriptedGateway(
            [
                _payload(5, 2, "first"),
                _payload(5, 2, "second"),
            ]
        )
        j = self._judge(gw)
        _run(
            j.judge_pair(
                prompt=PROMPT,
                chosen_text=CHOSEN,
                rejected_text=REJECTED_BAD_NUMBER,
                evidence_text=EVIDENCE,
            )
        )
        assert len(gw.calls) == 2

        # Which CONTENT is presented under the FIRST label — the labels
        # themselves sit at fixed template positions, so only the payload
        # under them reveals the presentation order.
        def first_section(user: str) -> str:
            return user.split("FIRST ANSWER:", 1)[1].split("SECOND ANSWER:", 1)[0]

        first_positions = []
        for call in gw.calls:
            u = call["user"]
            assert EVIDENCE in u and PROMPT in u
            first_positions.append(CHOSEN in first_section(u))
        # start order is randomized, the repeat is always its reversal:
        # whichever way call one landed, call two must present the other side.
        assert first_positions[0] != first_positions[1]

    def test_order_disagreement_routes_to_review(self):
        gw = _ScriptedGateway(
            [
                _payload(5, 2, "first"),  # prefers chosen
                _payload(2, 5, "first"),  # prefers REJECTED when it is second -> flip
            ]
        )
        j = self._judge(gw)
        out = _run(
            j.judge_pair(
                prompt=PROMPT,
                chosen_text=CHOSEN,
                rejected_text=REJECTED_BAD_NUMBER,
                evidence_text=EVIDENCE,
                force_chosen_first=True,
            )
        )
        assert out.verdict == "review"
        assert "judge_order_disagreement" in out.reason_codes

    def test_insufficient_margin_routes_to_review(self):
        gw = _ScriptedGateway(
            [
                _payload(4, 4, "tie"),
                _payload(4, 4, "tie"),
            ]
        )
        j = self._judge(gw)
        out = _run(
            j.judge_pair(
                prompt=PROMPT,
                chosen_text=CHOSEN,
                rejected_text=REJECTED_BAD_NUMBER,
                evidence_text=EVIDENCE,
                force_chosen_first=True,
            )
        )
        assert out.verdict == "review"
        assert any("margin" in rc for rc in out.reason_codes)

    def test_style_only_defect_is_not_a_real_defect(self):
        gw = _ScriptedGateway(
            [
                _payload(5, 4, "first", defects_second=["style_only_difference"]),
                _payload(4, 5, "second", defects_first=["style_only_difference"]),
            ]
        )
        j = self._judge(gw, min_preference_margin=0.4)
        out = _run(
            j.judge_pair(
                prompt=PROMPT,
                chosen_text=CHOSEN,
                rejected_text=REJECTED_BAD_NUMBER.replace("15", "40").replace(
                    "monthly", "annually"
                ),
                evidence_text=EVIDENCE,
                force_chosen_first=True,
            )
        )
        assert out.verdict in ("review", "invalid")
        assert "rejected_defect_not_classified" in out.reason_codes

    def test_length_signature_detected(self):
        verbose_rejected = REJECTED_BAD_NUMBER + " " + "Additionally, " * 60 + "etc."
        gw = _ScriptedGateway(
            [
                _payload(5, 2, "first", defects_second=["factually_incorrect_number_or_unit"]),
                _payload(2, 5, "second", defects_first=["factually_incorrect_number_or_unit"]),
            ]
        )
        j = self._judge(gw)
        out = _run(
            j.judge_pair(
                prompt=PROMPT,
                chosen_text=CHOSEN,
                rejected_text=verbose_rejected,
                evidence_text=EVIDENCE,
                force_chosen_first=True,
            )
        )
        assert "length_signature" in out.reason_codes
        assert out.verdict == "review"

    def test_both_good_never_passes_as_preference(self):
        gw = _ScriptedGateway(
            [
                _payload(5, 4, "first", defects_second=["omits_requirement"]),
                _payload(4, 5, "second", defects_first=["omits_requirement"]),
            ]
        )
        j = self._judge(gw, min_preference_margin=0.4)
        out = _run(
            j.judge_pair(
                prompt=PROMPT,
                chosen_text=CHOSEN,
                rejected_text="Calibration takes 40 minutes per unit; "
                "annual repetition is required.",
                evidence_text=EVIDENCE,
                force_chosen_first=True,
            )
        )
        assert out.verdict != "valid"
        assert "both_answers_good" in out.reason_codes

    def test_both_bad_is_invalid(self):
        gw = _ScriptedGateway(
            [
                _payload(2, 1, "second"),
                _payload(1, 2, "first"),
            ]
        )
        j = self._judge(gw)
        out = _run(
            j.judge_pair(
                prompt=PROMPT,
                chosen_text="Wrong wrong wrong.",
                rejected_text="Also wrong.",
                evidence_text=EVIDENCE,
                force_chosen_first=True,
            )
        )
        assert out.verdict == "invalid"
        assert "both_answers_bad" in out.reason_codes

    def test_chosen_below_absolute_floor_invalid(self):
        gw = _ScriptedGateway(
            [
                _payload(2, 1, "first"),
                _payload(1, 2, "second"),
            ]
        )
        j = self._judge(gw)
        out = _run(
            j.judge_pair(
                prompt=PROMPT,
                chosen_text="Garbage.",
                rejected_text="Worse garbage.",
                evidence_text=EVIDENCE,
                force_chosen_first=True,
            )
        )
        assert out.verdict == "invalid"
        assert "chosen_below_absolute_floor" in out.reason_codes

    def test_judge_failure_yields_review_not_valid(self):
        class _Dead:
            verifier_model = "x"

            async def judge(self, **kw):
                raise RuntimeError("down")

        j = self._judge(_Dead())
        out = _run(
            j.judge_pair(
                prompt=PROMPT,
                chosen_text=CHOSEN,
                rejected_text=REJECTED_BAD_NUMBER,
                evidence_text=EVIDENCE,
            )
        )
        assert out.verdict == "review"
        assert "judge_unavailable" in out.reason_codes

    def test_invalid_json_yields_review(self):
        # both orders run; BOTH must return unparseable output for the
        # invalid-output classification (a scripted queue that runs dry after
        # call one is a judge AVAILABILITY failure, not an output failure).
        gw = _ScriptedGateway(
            [
                "I prefer the first answer, it looks better.",
                "The second answer is clearly the better one.",
            ]
        )
        j = self._judge(gw)
        out = _run(
            j.judge_pair(
                prompt=PROMPT,
                chosen_text=CHOSEN,
                rejected_text=REJECTED_BAD_NUMBER,
                evidence_text=EVIDENCE,
            )
        )
        assert out.verdict == "review"
        assert "judge_output_invalid" in out.reason_codes

    def test_empty_side_no_signal(self):
        gw = _ScriptedGateway([])
        j = self._judge(gw)
        out = _run(
            j.judge_pair(
                prompt=PROMPT, chosen_text=CHOSEN, rejected_text="", evidence_text=EVIDENCE
            )
        )
        assert out.verdict == "review"
        assert gw.calls == [], "no judge call should fire for empty input"


class TestNoAutoPerfectSignal:
    def test_judgement_defaults_are_fail_closed(self):
        """A PairwiseJudgement that never ran a judge is review/0.0-margin —
        never verdict='valid' with a perfect signal."""
        bare = PairwiseJudgement(verdict="invalid")
        d = bare.to_dict()
        assert d["verdict"] == "invalid"
        assert d["confidence"] == 0.0
        assert d["preference_margin"] == 0.0

    def test_gateway_without_judge_rejected_at_construction(self):
        with pytest.raises(TypeError, match="judge"):
            CertifiedPairwiseJudge(object())

    def test_to_dict_has_full_lineage_fields(self):
        required = {
            "verdict",
            "preference_margin",
            "order_consistent",
            "chosen_absolute",
            "rejected_absolute",
            "rejected_defect_codes",
            "judge_identity",
            "prompt_template_version",
            "schema_hash",
            "confidence",
            "reason_codes",
            "rationale",
        }
        assert required <= set(PairwiseJudgement(verdict="review").to_dict())


class TestPreferenceValidatorIntegration:
    def _example(self):
        from knovaryn.domain.schemas import CanonicalMessage, Topology, TrainingExample

        ex = TrainingExample(
            id="ex-pref-1",
            project_id="p1",
            topology=Topology.preference,
            system_messages=[],
            prompt_messages=[CanonicalMessage(role="user", content=PROMPT)],
            chosen_messages=[CanonicalMessage(role="assistant", content=CHOSEN)],
            rejected_messages=[CanonicalMessage(role="assistant", content=REJECTED_BAD_NUMBER)],
            source_span_ids=["sp-1"],
        )
        return ex

    def test_certified_profile_demotes_on_order_disagreement(self):
        from knovaryn.pipeline.quality.validators import PreferenceValidator, ValidatorContext

        gw = _ScriptedGateway(
            [
                _payload(5, 2, "first"),
                _payload(2, 5, "first"),  # disagreement after orientation
            ]
        )
        v = PreferenceValidator(
            preference_profile="certified-pairwise",
            gateway=gw,
            judge=CertifiedPairwiseJudge(gw, model="pref-judge/1b"),
        )
        ctx = ValidatorContext(source_texts={"sp-1": EVIDENCE}, policy_version="1")
        result = _run(v.assess(self._example(), ctx))
        assert result.score < 1.0
        assert "certified_pair_review" in result.reason_codes or any(
            "disagreement" in rc for rc in result.reason_codes
        )

    def test_heuristic_profile_unchanged_no_judge_calls(self):
        from knovaryn.pipeline.quality.validators import PreferenceValidator, ValidatorContext

        gw = _ScriptedGateway([])
        v = PreferenceValidator(preference_profile="heuristic", gateway=gw)
        ctx = ValidatorContext(source_texts={"sp-1": EVIDENCE}, policy_version="1")
        _run(v.assess(self._example(), ctx))
        assert gw.calls == []

    def test_config_default_is_heuristic(self):
        from knovaryn.domain.config import load_config

        cfg = load_config()
        assert (cfg.get("preference") or {}).get("profile") == "heuristic"
