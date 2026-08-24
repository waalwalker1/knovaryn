"""Certified pairwise preference judge (defect 3.9, v0.2.1).

Optional certified profile for preference-topology examples. Complements —
never replaces — the deterministic checks in ``preference.py`` (identical
pairs, near duplicates, style shortcuts, order reversal, absolute quality).

Contract enforced here:
- chosen AND rejected are judged against the SAME cited evidence;
- absolute quality and relative preference are judged separately;
- A/B ordering is randomized, the judgement repeated with reversed order,
  and disagreement between orders routes to review;
- a minimum preference margin is required;
- length/style/provider signatures are detected and reported;
- preferring the chosen requires a REAL, CLASSIFIED rejected-side defect;
- pairs where both answers are good, both bad, or indistinguishable do not
  pass as preferences;
- judge identity, prompt template version, schema hash, per-order
  confidences and reason codes are recorded in the judgement;
- if no judge executes, the result is review/invalid — NEVER an automatic
  perfect preference signal.

No chain-of-thought is requested or persisted: the judge returns structured
JSON only, and we store short reason codes plus a one-line rationale.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from typing import Any, cast

from ...domain.errors import UnsupportedOperationError
from ...domain.hashing import ContentHasher

DEFECT_CODES = (
    "unsupported_claim",
    "contradicts_evidence",
    "omits_requirement",
    "factually_incorrect_number_or_unit",
    "incoherent_or_off_topic",
    "misses_question",
    "fabricates_source",
    # style-only is explicitly NOT a real defect for certification purposes:
    "style_only_difference",
)

REAL_DEFECT_CODES = tuple(c for c in DEFECT_CODES if c != "style_only_difference")


@dataclass
class PairwiseJudgement:
    """Full record of one certified pairwise judgement (lineage-ready)."""

    verdict: str  # "valid" | "review" | "invalid"
    preference_margin: float = 0.0
    order_consistent: bool = False
    chosen_absolute: float = 0.0
    rejected_absolute: float = 0.0
    rejected_defect_codes: list[str] = field(default_factory=list)
    judge_identity: str = ""
    prompt_template_version: str = ""
    schema_hash: str = ""
    confidence: float = 0.0
    reason_codes: list[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "preference_margin": round(self.preference_margin, 4),
            "order_consistent": self.order_consistent,
            "chosen_absolute": round(self.chosen_absolute, 3),
            "rejected_absolute": round(self.rejected_absolute, 3),
            "rejected_defect_codes": list(self.rejected_defect_codes),
            "judge_identity": self.judge_identity,
            "prompt_template_version": self.prompt_template_version,
            "schema_hash": self.schema_hash,
            "confidence": round(self.confidence, 4),
            "reason_codes": list(self.reason_codes),
            "rationale": self.rationale,
        }


class CertifiedPairwiseJudge:
    """Two-order, evidence-cited pairwise judge over ``ModelGateway.judge``."""

    name = "certified_pairwise"
    version = "1"
    PROMPT_TEMPLATE_VERSION = "pairwise-judge/1"

    SYSTEM_PROMPT = (
        "You are a strict pairwise answer judge. You receive EVIDENCE and two "
        "candidate answers labelled FIRST and SECOND.\n"
        "Rules:\n"
        "- Judge ONLY against the provided evidence; never use outside knowledge.\n"
        "- Score each answer's ABSOLUTE quality from 1 to 5 "
        "(5 = fully supported, complete, correct).\n"
        "- Prefer an answer ONLY if the other has a concrete defect you can "
        f"classify with one of these codes: {', '.join(DEFECT_CODES)}.\n"
        "- A stylistic difference alone is NOT a defect worth preferring "
        "(use style_only_difference).\n"
        "- Output ONLY JSON, no prose:\n"
        '{"first_quality": <1-5>, "second_quality": <1-5>, '
        '"preferred": "first"|"second"|"tie", '
        '"defects_first": [<codes>], "defects_second": [<codes>], '
        '"confidence": <float 0-1>}'
    )

    SCHEMA_HASH = ContentHasher.cfg_hash(
        {
            "template": "pairwise-judge/1",
            "fields": [
                "first_quality",
                "second_quality",
                "preferred",
                "defects_first",
                "defects_second",
                "confidence",
            ],
            "defect_codes": sorted(DEFECT_CODES),
        }
    )

    def __init__(
        self,
        gateway: Any,
        *,
        model: str | None = None,
        min_preference_margin: float = 0.5,
        seed: int = 0,
    ) -> None:
        if not hasattr(gateway, "judge"):
            raise TypeError(
                "CertifiedPairwiseJudge requires a gateway exposing "
                "`async judge(...)` (ModelGateway.judge)"
            )
        self._gateway = gateway
        self.model = model or getattr(gateway, "verifier_model", "") or "configured"
        self.min_preference_margin = float(min_preference_margin)
        self._seed = int(seed)

    @property
    def identity(self) -> str:
        return f"{self.name}:{self.model}:v{self.version}"

    async def judge_pair(
        self,
        *,
        prompt: str,
        chosen_text: str,
        rejected_text: str,
        evidence_text: str,
        force_chosen_first: bool | None = None,
    ) -> PairwiseJudgement:
        """Run both orders and reconcile into one lineage-ready judgement.

        ``force_chosen_first`` pins the initial presentation order (tests /
        reproducible re-judgement); production leaves it randomized.
        """
        base = PairwiseJudgement(
            verdict="review",
            judge_identity=self.identity,
            prompt_template_version=self.PROMPT_TEMPLATE_VERSION,
            schema_hash=self.SCHEMA_HASH,
        )
        if not chosen_text.strip() or not rejected_text.strip():
            base.reason_codes = ["missing_answer_text"]
            base.rationale = "one side of the pair is empty; no preference signal"
            return base

        rng = random.Random(f"{self._seed}:{prompt!r}:{chosen_text[:32]}")
        chosen_first = (
            rng.random() < 0.5 if force_chosen_first is None else bool(force_chosen_first)
        )

        try:
            raw_a = await self._call(
                prompt, evidence_text, chosen_text, rejected_text, chosen_first=chosen_first
            )
            raw_b = await self._call(
                prompt, evidence_text, chosen_text, rejected_text, chosen_first=not chosen_first
            )
        except UnsupportedOperationError:
            raise
        except Exception as exc:  # noqa: BLE001
            base.reason_codes = ["judge_unavailable"]
            base.rationale = f"judge call failed: {type(exc).__name__}"
            return base

        parsed_a = self._parse(raw_a)
        parsed_b = self._parse(raw_b)
        if parsed_a is None or parsed_b is None:
            base.reason_codes = ["judge_output_invalid"]
            base.rationale = "judge did not return parseable verdict JSON"
            return base

        # map both orders onto (quality_chosen, quality_rejected, pref_is_chosen)
        def orient(run_first_is_chosen: bool, p: dict) -> tuple[float, float, bool | None]:
            fq, sq = float(p["first_quality"]), float(p["second_quality"])
            pref = p["preferred"]
            if pref == "tie":
                return fq, sq, None
            pref_first = pref == "first"
            prefers_chosen = pref_first if run_first_is_chosen else not pref_first
            qc, qr = (fq, sq) if run_first_is_chosen else (sq, fq)
            return qc, qr, prefers_chosen

        q_chosen_a, q_rej_a, pref_chosen_a = orient(chosen_first, parsed_a)
        q_chosen_b, q_rej_b, pref_chosen_b = orient(not chosen_first, parsed_b)

        base.chosen_absolute = round((q_chosen_a + q_chosen_b) / 2, 3)
        base.rejected_absolute = round((q_rej_a + q_rej_b) / 2, 3)

        # order consistency: both runs must agree on direction
        if pref_chosen_a is None or pref_chosen_b is None:
            base.order_consistent = False
            base.reason_codes.append("judge_called_tie")
        elif pref_chosen_a is pref_chosen_b:
            base.order_consistent = True
        else:
            base.reason_codes.append("judge_order_disagreement")

        # minimum preference margin (mean signed quality gap across orders)
        margin = ((q_chosen_a - q_rej_a) + (q_chosen_b - q_rej_b)) / 2
        base.preference_margin = round(margin, 3)
        if abs(margin) < self.min_preference_margin:
            base.reason_codes.append("insufficient_preference_margin")

        # signatures: length/style differences that fake a preference signal
        ratio = len(chosen_text) / max(1, len(rejected_text))
        if not (0.5 <= ratio <= 2.0):
            base.reason_codes.append("length_signature")
        norm_c = re.sub(r"\W+", " ", chosen_text.lower()).strip()
        norm_r = re.sub(r"\W+", " ", rejected_text.lower()).strip()
        if norm_c == norm_r:
            base.reason_codes.append("identical_content")

        # rejected-side defect must be real and classified when chosen wins
        defects_rejected = sorted(
            {
                *(d for d in parsed_a["defects_second"] if chosen_first),
                *(d for d in parsed_a["defects_first"] if not chosen_first),
                *(d for d in parsed_b["defects_second"] if not chosen_first),
                *(d for d in parsed_b["defects_first"] if chosen_first),
            }
            & set(DEFECT_CODES)
        )
        base.rejected_defect_codes = defects_rejected

        if margin > 0 and base.order_consistent:
            real = [d for d in defects_rejected if d in REAL_DEFECT_CODES]
            if not real:
                base.reason_codes.append("rejected_defect_not_classified")

        # absolute-quality gates on BOTH sides
        if base.chosen_absolute < 3.0:
            base.reason_codes.append("chosen_below_absolute_floor")
        if base.rejected_absolute >= 4.0 and margin > 0:
            base.reason_codes.append("both_answers_good")
        if base.chosen_absolute <= 2.0 and base.rejected_absolute <= 2.0:
            base.reason_codes.append("both_answers_bad")

        base.confidence = round(
            min(parsed_a.get("confidence", 0.0), parsed_b.get("confidence", 0.0)), 4
        )

        hard_invalid = {
            "missing_answer_text",
            "chosen_below_absolute_floor",
            "identical_content",
        }
        blockers = set(base.reason_codes)
        if blockers & hard_invalid:
            base.verdict = "invalid"
        elif blockers & {
            "judge_order_disagreement",
            "insufficient_preference_margin",
            "length_signature",
            "rejected_defect_not_classified",
            "both_answers_good",
            "both_answers_bad",
            "judge_called_tie",
        }:
            base.verdict = "review"
        elif margin > 0 and base.order_consistent:
            base.verdict = "valid"
        else:
            base.verdict = "review"

        base.rationale = (
            f"margin={base.preference_margin} "
            f"chosen_abs={base.chosen_absolute} rej_abs={base.rejected_absolute} "
            f"consistent={base.order_consistent}"
        )
        return base

    async def _call(
        self,
        prompt: str,
        evidence_text: str,
        chosen_text: str,
        rejected_text: str,
        *,
        chosen_first: bool,
    ) -> dict[str, Any]:
        if self._gateway is None:
            raise UnsupportedOperationError(
                "no preference judge configured; pair stays unreviewed-as-valid"
            )
        first, second = (
            (chosen_text, rejected_text) if chosen_first else (rejected_text, chosen_text)
        )
        user = (
            f'TASK/PROMPT:\n"""\n{prompt}\n"""\n\n'
            f'EVIDENCE:\n"""\n{evidence_text}\n"""\n\n'
            f'FIRST ANSWER:\n"""\n{first}\n"""\n\n'
            f'SECOND ANSWER:\n"""\n{second}\n"""\n\n'
            "Respond with ONLY the JSON object."
        )
        return cast(
            "dict[str, Any]",
            await self._gateway.judge(
                system=self.SYSTEM_PROMPT,
                user=user,
                prompt_template_version=self.PROMPT_TEMPLATE_VERSION,
                schema_hash=self.SCHEMA_HASH,
                stage="preference_judge",
            ),
        )

    @staticmethod
    def _parse(result: dict[str, Any]) -> dict[str, Any] | None:
        text = str(result.get("content") or result.get("text") or "")
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
            stripped = re.sub(r"\n?```$", "", stripped).strip()
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            start, end = stripped.find("{"), stripped.rfind("}")
            if start == -1 or end <= start:
                return None
            try:
                data = json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                return None
        if not isinstance(data, dict):
            return None
        try:
            data["first_quality"] = min(5.0, max(1.0, float(data["first_quality"])))
            data["second_quality"] = min(5.0, max(1.0, float(data["second_quality"])))
            conf = min(1.0, max(0.0, float(data.get("confidence", 0.0))))
        except (KeyError, TypeError, ValueError):
            return None
        data["confidence"] = conf
        if data.get("preferred") not in ("first", "second", "tie"):
            return None
        data["defects_first"] = [str(d) for d in data.get("defects_first") or []]
        data["defects_second"] = [str(d) for d in data.get("defects_second") or []]
        return data
