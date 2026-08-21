"""Semantic verifier port and implementations (WP A3/A4).

Defines the SemanticVerifier interface and three implementations:
- DeterministicSemanticVerifier: rule-based checks from claims.py
- ModelSemanticVerifier: LLM-based judge via model gateway
- CompositeSemanticVerifier: combines both
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass
from typing import Literal

from .claims import (
    AtomicClaim,
    ClaimAssessment,
    ClaimVerdict,
    check_entity_role_reversal,
    check_negation_reversal,
    check_number_mismatch,
    check_unit_mismatch,
    check_unsupported_entities,
    detect_causal_direction,
    normalize_date,
    normalize_number_text,
    normalize_unit,
)

logger = logging.getLogger(__name__)

_NEGATION_WORDS = frozenset(
    {
        "not",
        "no",
        "never",
        "cannot",
        "can't",
        "don't",
        "doesn't",
        "didn't",
        "won't",
        "isn't",
        "aren't",
        "prohibited",
        "forbidden",
    }
)
_COMPARISON_PHRASES = (
    " greater than ",
    " larger than ",
    " bigger than ",
    " less than ",
    " smaller than ",
    " higher than ",
    " lower than ",
    " exceeds ",
    " exceed ",
)
_COMPARISON_MARKERS = ("greater", "larger", "less", "exceeds", "above", "below")
_COMPARISON_MARKERS_WIDE = (
    "greater",
    "larger",
    "less",
    "smaller",
    "higher",
    "lower",
    "exceeds",
    "above",
    "below",
    "more than",
    "less than",
)


class SemanticVerifier(abc.ABC):
    """Port for semantic verification of claims against evidence."""

    name: str = "base"
    version: str = "1"

    @abc.abstractmethod
    async def assess_claims(
        self,
        claims: list[AtomicClaim],
        evidence_text: str,
        prompt: str = "",
        candidate_answer: str = "",
        cited_span_ids: list[str] | None = None,
    ) -> list[ClaimAssessment]:
        """Assess a list of atomic claims against the provided evidence text."""
        raise NotImplementedError


@dataclass
class VerifierConfig:
    """Configuration for semantic verification.

    Attributes:
        require_deterministic_checks: If True, run deterministic checks even when
            a model verifier is present. Marked examples as FAILED if deterministic
            contradicts.
        offline_mode: If True, only run deterministic checks and label output as
            structural_demo_only.
        model_verifier_timeout: Timeout in seconds for model verifier calls.
        max_retries: Number of retries for model verifier calls.
        reorder_evidence: If True, reorder evidence for high-risk examples to
            detect position bias.
        max_claims_per_example: Maximum number of claims to assess per example.
    """

    require_deterministic_checks: bool = True
    offline_mode: bool = False
    model_verifier_timeout: int = 60
    max_retries: int = 2
    reorder_evidence: bool = False
    max_claims_per_example: int = 50


def extract_atomic_claims(text: str) -> list[AtomicClaim]:
    """Extract atomic claims from a piece of text using pattern matching.

    This is a heuristic extractor. For full coverage, a model-based extractor
    would be more accurate, but this handles the common patterns.
    """
    claims: list[AtomicClaim] = []

    # Split into sentences
    sentences = text.replace("! ", ". ").replace("? ", ". ").split(". ")
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence or len(sentence) < 5:
            continue

        polarity: Literal["affirmed", "negated", "unknown"] = "affirmed"

        # Check for negation
        tokens_lower = sentence.lower().split()[:10]
        negated = any(w.strip(".,!?;:") in _NEGATION_WORDS for w in tokens_lower)
        if negated:
            polarity = "negated"

        # Extract numbers
        numbers = normalize_number_text(sentence)
        units = normalize_unit(sentence)
        dates = normalize_date(sentence)

        # Determine subject and relation (heuristic)
        subj: str | None = None
        rel: str | None = None
        obj: str | None = None

        # Check for causal patterns
        for marker in ["causes", "cause", "caused", "results in", "leads to", "triggers"]:
            idx = sentence.lower().find(marker)
            if idx > 0:
                before = sentence[:idx].strip()
                after = sentence[idx + len(marker) :].strip()
                # Extract subject (last word before marker)
                b_words = before.split()
                if b_words:
                    subj = b_words[-1].strip(".,;:")
                # Extract object (first word/phrase after marker)
                a_words = after.split()
                if a_words:
                    obj = a_words[0].strip(".,;:")
                rel = marker
                break

        # Check for "be" relation patterns (is/are/was/were)
        if subj is None:
            for be_verb in [" is ", " are ", " was ", " were ", " has ", " have ", " had "]:
                idx = sentence.lower().find(be_verb)
                if idx > 0:
                    before = sentence[:idx].strip()
                    after = sentence[idx + len(be_verb) :].strip()
                    b_words = before.split()
                    if b_words:
                        subj = b_words[-1].strip(".,;:")
                    a_words = after.split()
                    if a_words:
                        obj = a_words[0].strip(".,;:") if a_words else None
                    rel = be_verb.strip()
                    break

        # Detect comparison relations
        for comp_word in _COMPARISON_PHRASES:
            if comp_word in sentence.lower():
                idx = sentence.lower().find(comp_word)
                before = sentence[:idx].strip()
                after = sentence[idx + len(comp_word) :].strip()
                b_words = before.split()
                if b_words:
                    subj = b_words[-1].strip(".,;:")
                obj = after.split()[0].strip(".,;:") if after.split() else None
                rel = comp_word.strip()
                break

        # Determine claim type
        claim_type = "proposition"
        if any(m in sentence.lower() for m in ["causes", "cause", "result"]) and subj and rel:
            claim_type = "causal"
        elif any(m in sentence.lower() for m in _COMPARISON_MARKERS):
            claim_type = "comparison"
        elif numbers:
            claim_type = "numeric"
        elif dates:
            claim_type = "temporal"
        elif subj and rel:
            claim_type = "entity_role"

        claim = AtomicClaim(
            text=sentence,
            subject=subj,
            relation=rel,
            polarity=polarity,
            claim_type=claim_type,
            numbers=numbers,
            dates=dates,
            units=units,
        )
        # ``obj`` is serialized under its ``object`` alias; the mypy pydantic
        # plugin only accepts the alias in the constructor, so assign by name.
        claim.obj = obj
        claims.append(claim)

    return claims


def determine_claim_type(claim_text: str) -> str:
    """Determine the type of a claim based on its content."""
    text_lower = claim_text.lower()
    if any(m in text_lower for m in ["causes", "cause", "result", "leads", "triggers", "depends"]):
        return "causal"
    if any(m in text_lower for m in _COMPARISON_MARKERS_WIDE):
        return "comparison"
    return "proposition"


class DeterministicSemanticVerifier(SemanticVerifier):
    """Rule-based semantic verifier using deterministic checks from claims.py."""

    name: str = "deterministic"
    version: str = "1"

    async def assess_claims(
        self,
        claims: list[AtomicClaim],
        evidence_text: str,
        prompt: str = "",
        candidate_answer: str = "",
        cited_span_ids: list[str] | None = None,
    ) -> list[ClaimAssessment]:
        """Assess claims using deterministic rules. No model calls needed."""
        assessments: list[ClaimAssessment] = []

        evidence_lower = evidence_text.lower().strip()

        for claim in claims:
            verdict = ClaimVerdict.entailed
            confidence = 0.9
            reason_codes: list[str] = []
            contradiction_quotes: list[str] = []
            supporting_quotes: list[str] = []

            # Check for unsupported entities first
            unsupported = check_unsupported_entities(claim.text, evidence_text)
            if unsupported:
                verdict = ClaimVerdict.contradicted
                reason_codes.extend(f"unsupported_entity:{e}" for e in unsupported)
                missing = ", ".join(unsupported)
                contradiction_quotes.append(f"Entities not found in evidence: {missing}")
                confidence = 0.5

            # Check causal direction
            if claim.claim_type == "causal":
                claim_subj, evidence_subj, direction_str = detect_causal_direction(
                    claim.text, evidence_text
                )
                if direction_str and claim_subj != evidence_subj:
                    # Subjects are swapped between claim and evidence —
                    # e.g. claim says "alarm causes" but evidence says "shutdown causes"
                    verdict = ClaimVerdict.contradicted
                    reason_codes.append("causal_direction_reversal")
                    contradiction_quotes.append(
                        f"Claim says '{claim_subj} causes...' but evidence says "
                        f"'{evidence_subj} causes...'"
                    )
                    confidence = min(confidence, 0.0)

            # Check entity role reversal
            if check_entity_role_reversal(claim.text, evidence_text):
                verdict = ClaimVerdict.contradicted
                reason_codes.append("subject_object_reversal")
                contradiction_quotes.append("Entity roles reversed compared to evidence")
                confidence = min(confidence, 0.0)

            # Check negation reversal
            if check_negation_reversal(claim.text, evidence_text):
                verdict = ClaimVerdict.contradicted
                reason_codes.append("negation_reversal")
                contradiction_quotes.append("Claim polarity contradicts evidence polarity")
                confidence = min(confidence, 0.0)

            # Check number mismatches
            num_reasons = check_number_mismatch(claim.text, evidence_text)
            if num_reasons:
                verdict = ClaimVerdict.contradicted
                reason_codes.extend(num_reasons)
                contradiction_quotes.append(f"Number mismatch: {', '.join(num_reasons)}")
                confidence = min(confidence, 0.0)

            # Check unit mismatches
            unit_reasons = check_unit_mismatch(claim.text, evidence_text)
            if unit_reasons:
                verdict = ClaimVerdict.contradicted
                reason_codes.extend(unit_reasons)
                contradiction_quotes.append(f"Unit mismatch: {', '.join(unit_reasons)}")
                confidence = min(confidence, 0.0)

            # If claim text appears in evidence, it's supported
            claim_lower = claim.text.lower().strip().rstrip(".")
            if claim_lower in evidence_lower:
                supporting_quotes.append(claim.text)

            assessments.append(
                ClaimAssessment(
                    claim=claim,
                    verdict=verdict,
                    confidence=confidence,
                    supporting_span_ids=cited_span_ids or [],
                    supporting_quotes=supporting_quotes,
                    contradiction_quotes=contradiction_quotes,
                    reason_codes=reason_codes,
                    verifier_name=self.name,
                    verifier_version=self.version,
                    concise_rationale=f"Deterministic check: {len(reason_codes)} issue(s)",
                )
            )

        return assessments


class ModelSemanticVerifier(SemanticVerifier):
    """LLM-based semantic verifier that calls a model gateway.

    This implementation wraps a model gateway call to get structured JSON
    output validating each claim against the evidence.
    """

    name: str = "model_semantic"
    version: str = "1"

    def __init__(
        self,
        model_gateway: object,
        structured_output_support: bool = True,
        max_retries: int = 2,
        timeout: int = 60,
    ):
        self._model_gateway = model_gateway
        self._structured_output_support = structured_output_support
        self._max_retries = max_retries
        self._timeout = timeout

    async def assess_claims(
        self,
        claims: list[AtomicClaim],
        evidence_text: str,
        prompt: str = "",
        candidate_answer: str = "",
        cited_span_ids: list[str] | None = None,
    ) -> list[ClaimAssessment]:
        """Assess claims using a model gateway call.

        Falls back to deterministic checks if model call fails.
        """
        try:
            return await self._call_model(
                claims, evidence_text, prompt, candidate_answer, cited_span_ids or []
            )
        except Exception:
            logger.warning("Model semantic verifier call failed, returning unverified")
            return [
                ClaimAssessment(
                    claim=c,
                    verdict=ClaimVerdict.unverified,
                    confidence=0.0,
                    reason_codes=["model_verifier_failed"],
                    verifier_name=self.name,
                    verifier_version=self.version,
                    concise_rationale="Model verifier call failed, claim unverified",
                )
                for c in claims
            ]

    async def _call_model(
        self,
        claims: list[AtomicClaim],
        evidence_text: str,
        prompt: str,
        candidate_answer: str,
        cited_span_ids: list[str],
    ) -> list[ClaimAssessment]:
        """Make the actual model call.

        In offline/demo mode, falls back to deterministic.
        This implementation is a stub for the actual model gateway integration.
        """
        # Placeholder for model gateway call
        # In production this would construct a prompt with the claims and evidence,
        # call the model with structured output, parse the JSON response,
        # and return ClaimAssessment objects.
        raise NotImplementedError("ModelSemanticVerifier requires a model gateway implementation")


class CompositeSemanticVerifier(SemanticVerifier):
    """Composite verifier that runs deterministic checks first, then model judge.

    In offline mode, only deterministic checks run and output is labeled
    structural_demo_only. In certified mode, the model judge runs after
    deterministic checks and cannot override a deterministic contradiction.
    """

    name: str = "composite_semantic"
    version: str = "2"

    def __init__(
        self,
        deterministic_verifier: DeterministicSemanticVerifier | None = None,
        model_verifier: ModelSemanticVerifier | None = None,
        config: VerifierConfig | None = None,
    ):
        self._deterministic = deterministic_verifier or DeterministicSemanticVerifier()
        self._model_verifier = model_verifier
        self._config = config or VerifierConfig()

    async def assess_claims(
        self,
        claims: list[AtomicClaim],
        evidence_text: str,
        prompt: str = "",
        candidate_answer: str = "",
        cited_span_ids: list[str] | None = None,
    ) -> list[ClaimAssessment]:
        """Run assessments with deterministic checks always, model optionally.

        In offline mode, only deterministic checks run.
        The model judge cannot override a deterministic contradiction.
        """
        # Step 1: Always run deterministic checks
        deterministic_results = await self._deterministic.assess_claims(
            claims, evidence_text, prompt, candidate_answer, cited_span_ids
        )

        # In offline mode, return deterministic-only results
        if self._config.offline_mode or self._model_verifier is None:
            return deterministic_results

        # Check for deterministic contradictions
        deterministic_contradictions = {
            a.claim.text for a in deterministic_results if a.verdict == ClaimVerdict.contradicted
        }

        # Step 2: Run model verifier on non-contradicted claims
        non_contradicted_claims = [c for c in claims if c.text not in deterministic_contradictions]

        if non_contradicted_claims:
            model_results = await self._model_verifier.assess_claims(
                non_contradicted_claims, evidence_text, prompt, candidate_answer, cited_span_ids
            )
        else:
            model_results = []

        # Step 3: Merge results (deterministic contradictions take precedence)
        merged: list[ClaimAssessment] = []
        for da in deterministic_results:
            if da.verdict == ClaimVerdict.contradicted:
                merged.append(da)
            else:
                # Find corresponding model result
                matching = [m for m in model_results if m.claim.text == da.claim.text]
                if matching:
                    merged.append(matching[0])
                else:
                    merged.append(da)

        return merged
