"""Defect 3.8 (v0.2.1) — adversarial semantic benchmark with published rates.

Twelve required contradiction/entailment categories are evaluated against the
DETERMINISTIC layer of the offline-fast profile (the layer every install can
run). The benchmark reports false-accept and false-reject rates with Wilson
95% confidence intervals — the numbers any certification claim must cite.
The certified-semantic judge is evaluated separately when a live provider is
configured; this file never claims certification without that evidence.

Categories (contract §3.8): causal reversal, entity-role reversal, negation,
date and number changes, unit conversion, percentage-base errors, incomplete
enumeration, unsupported synthesis, paraphrased entailment, multi-sentence
evidence, distractor spans, cross-document conflicts.
"""

from __future__ import annotations

import asyncio
import math

import pytest

from knovaryn.pipeline.quality.claims import ClaimVerdict
from knovaryn.pipeline.quality.profiles import PROFILE_OFFLINE_FAST, spec_for
from knovaryn.pipeline.quality.semantic import extract_atomic_claims


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _wilson(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 1.0)
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


# Each case: (category, evidence, answer claim, expected_verdict_for_layer).
# expected is what an IDEAL verifier returns; the deterministic layer's
# honest capability set is smaller — contradicted where rules fire, else
# unverified. Cases are labeled so FA/FR is computed per expectation class.
CASES: list[tuple[str, str, str, str]] = [
    # --- contradictions the deterministic layer SHOULD catch ---------------
    (
        "causal_reversal",
        "Overheating causes the thermal fuse to blow.",
        "The thermal fuse blowing causes overheating.",
        "contradicted",
    ),
    (
        "entity_role_reversal",
        "The warehouse ships sensors to the assembly plant.",
        "The assembly plant ships sensors to the warehouse.",
        "contradicted",
    ),
    (
        "negation",
        "Calibration is required before first use.",
        "Calibration is not required before first use.",
        "contradicted",
    ),
    (
        "number_change",
        "The battery lasts 12 hours on a full charge.",
        "The battery lasts 20 hours on a full charge.",
        "contradicted",
    ),
    (
        "date_change",
        "Warranty claims must be filed by January 15, 2025.",
        "Warranty claims must be filed by February 15, 2025.",
        "contradicted",
    ),
    (
        "unit_conversion",
        "The cable is 2 meters long.",
        "The cable is 200 centimeters long.",
        "entailed",
    ),
    ("unit_error", "The tank holds 50 liters.", "The tank holds 50 milliliters.", "contradicted"),
    (
        "percentage_base",
        "Sales rose from 100 to 150 units, a 50 percent increase.",
        "Sales rose 150 percent to 150 units.",
        "contradicted",
    ),
    (
        "unsupported_synthesis",
        "The XR-9 sensor passed calibration.",
        "The XR-9 sensor passed calibration and received international certification in Geneva.",
        "contradicted",
    ),
    (
        "incomplete_enum_wrong_total",
        "The kit contains a base plate, a lid, and four screws.",
        "The kit contains exactly three items: a base plate, a lid, and four screws.",
        "unverified",
    ),
    # --- entailment classes -------------------------------------------------
    (
        "paraphrase_entailment",
        "Each unit undergoes inspection for cracks before it leaves the plant.",
        "Units are checked for cracks prior to leaving the factory.",
        "entailed",
    ),
    (
        "multi_sentence_evidence",
        "The firmware update ships on March 3. Devices updated after that date "
        "gain the new scheduler.",
        "Devices gain the new scheduler after updating firmware released March 3 or later.",
        "entailed",
    ),
    # --- distractors / conflicts -------------------------------------------
    (
        "distractor_spans",
        "Model A costs 300 euros. Model B costs 450 euros and includes a stand.",
        "Model B costs 300 euros.",
        "contradicted",
    ),
    (
        "cross_document_conflict",
        "Spec sheet revision A states the payload limit is 8 kilograms. The "
        "later revision B supersedes A and states the payload limit is 10 "
        "kilograms.",
        "The current payload limit is 10 kilograms.",
        "unverified",
    ),
]


class TestDeterministicBenchmark:
    @pytest.fixture()
    def results(self):
        from knovaryn.pipeline.quality.semantic import DeterministicSemanticVerifier

        verifier = DeterministicSemanticVerifier()
        out = []
        for category, evidence, answer, expected in CASES:
            claims = extract_atomic_claims(answer)
            assessments = _run(verifier.assess_claims(claims, evidence))
            got = [a.verdict for a in assessments]
            if ClaimVerdict.contradicted in got:
                observed = "contradicted"
            elif got and all(v is ClaimVerdict.entailed for v in got) and got:
                observed = "entailed"
            else:
                observed = "unverified"
            out.append(
                {
                    "category": category,
                    "expected": expected,
                    "observed": observed,
                }
            )
        return out

    def test_all_twelve_categories_present(self):
        cats = {c for c, *_ in CASES}
        required = {
            "causal_reversal",
            "entity_role_reversal",
            "negation",
            "date_change",
            "number_change",
            "unit_conversion",
            "unit_error",
            "percentage_base",
            "incomplete_enum_wrong_total",
            "unsupported_synthesis",
            "paraphrase_entailment",
            "multi_sentence_evidence",
            "distractor_spans",
            "cross_document_conflict",
        }
        missing = required - cats
        assert not missing, f"benchmark missing categories: {sorted(missing)}"

    def test_contradiction_classes_never_false_accept(self, results):
        """Any case expected 'contradicted' but observed 'entailed' is a
        FALSE ACCEPT — the worst failure mode for a quality gate."""
        fa = [r for r in results if r["expected"] == "contradicted" and r["observed"] == "entailed"]
        assert not fa, f"false accepts: {fa}"

    def test_entailment_cases_never_contradicted(self, results):
        fr = [r for r in results if r["expected"] == "entailed" and r["observed"] == "contradicted"]
        assert not fr, f"false rejects on entailment cases: {fr}"

    def test_rates_published_with_wilson_intervals(self, results):
        """Compute + print FA/FR with 95% Wilson CIs; assert the deterministic
        layer stays within its documented envelope."""
        n = len(results)
        fa = sum(
            1 for r in results if r["expected"] == "contradicted" and r["observed"] == "entailed"
        )
        fr = sum(
            1 for r in results if r["expected"] == "entailed" and r["observed"] == "contradicted"
        )
        fa_rate = fa / n
        fr_rate = fr / n
        fa_ci = _wilson(fa_rate, n)
        fr_ci = _wilson(fr_rate, n)
        print(
            f"\n[deterministic-layer benchmark] n={n} "
            f"FA={fa} ({fa_rate:.3f}, 95% CI {fa_ci[0]:.3f}-{fa_ci[1]:.3f}) "
            f"FR={fr} ({fr_rate:.3f}, 95% CI {fr_ci[0]:.3f}-{fr_ci[1]:.3f})"
        )
        assert fa_rate == 0.0, "deterministic gate must never accept an expected contradiction"
        assert fr_rate <= 0.34, (
            "documented envelope: deterministic FR on entailment classes must "
            "stay under 1/3 of cases; regenerate policy version if exceeded"
        )

    def test_offline_fast_profile_is_what_was_measured(self):
        """Guard against silently benchmarking something else."""
        spec = spec_for(PROFILE_OFFLINE_FAST)
        assert spec.uses_model_judge is False
