"""Quality validation framework (spec §13, §14).

Validators turn a training example + its supporting evidence into a
:class:`QualityAssessment`. Each validator is versioned and returns a score
plus reason codes. The framework folds per-validator results into an overall
accept/review/reject decision using :class:`AcceptancePolicy`.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

from ...domain.policies import AcceptancePolicy, preference_is_trivially_separable
from ...domain.schemas import (
    QualityAssessment,
    QualityStatus,
    Topology,
    TrainingExample,
    Verification,
)
from .claims import ClaimVerdict
from .semantic import DeterministicSemanticVerifier, extract_atomic_claims


@dataclass
class ValidatorContext:
    source_texts: dict[str, str] = field(default_factory=dict)  # span_id -> quoted text
    policy_version: str = "1"


class BaseValidator(abc.ABC):
    name: str = "base"
    version: str = "1"

    @abc.abstractmethod
    async def assess(self, example: TrainingExample, ctx: ValidatorContext) -> QualityAssessment:
        raise NotImplementedError


def _status(score: float) -> QualityStatus:
    if score >= 0.8:
        return QualityStatus.accepted
    if score >= 0.5:
        return QualityStatus.review
    return QualityStatus.rejected


def _verify_state(score: float, floor: float) -> Verification:
    """WP C1: a dimension is ``verified`` only when executed AND above its floor."""
    return Verification.verified if score >= floor else Verification.failed


class GroundingValidator(BaseValidator):
    """Faithfulness: the assistant answer must be traceable to the evidence."""

    name = "grounding"
    version = "1"

    async def assess(self, example: TrainingExample, ctx: ValidatorContext) -> QualityAssessment:
        answer_text = _assistant_text(example)
        # Evidence-scoped grounding (P0-3/C2): evaluate ONLY the spans this
        # example cites, never the whole project. Uncited-but-present text must
        # not be allowed to "ground" an answer, otherwise cross-document
        # contamination passes.
        cited = [ctx.source_texts[s] for s in example.source_span_ids if s in ctx.source_texts]
        evidence_text = " ".join(cited)
        score, reasons = _fractional_overlap(answer_text, evidence_text)
        if not evidence_text.strip():
            score = 0.0
            reasons = ["no_cited_evidence"]
        return QualityAssessment(
            id="",
            example_id=example.id,
            validator_name=self.name,
            validator_version=self.version,
            policy_version=ctx.policy_version,
            status=_status(score),
            verify_state=_verify_state(score, 0.9),  # WP C1: grounding is a hard floor
            score=score,
            reason_codes=reasons,
            concise_rationale=f"grounding score {score:.2f}",
        )


class CompletenessValidator(BaseValidator):
    """Completeness: answer length is within a sane band of the question+evidence."""

    name = "completeness"
    version = "1"

    async def assess(self, example: TrainingExample, ctx: ValidatorContext) -> QualityAssessment:
        answer_text = _assistant_text(example)
        prompt_text = _prompt_text(example)
        ans_tok = max(len(answer_text.split()), 1)
        prompt_tok = max(len(prompt_text.split()), 1)
        ratio = ans_tok / prompt_tok if prompt_tok else 0.0
        if answer_text and 0.05 <= ratio <= 8.0:
            score = 1.0
            reasons: list[str] = []
        elif not answer_text:
            score = 0.0
            reasons = ["empty_answer"]
        else:
            score = 0.6
            reasons = ["length_out_of_band"]
        return QualityAssessment(
            id="",
            example_id=example.id,
            validator_name=self.name,
            validator_version=self.version,
            policy_version=ctx.policy_version,
            status=_status(score),
            verify_state=_verify_state(score, 0.8),
            score=score,
            reason_codes=reasons,
            concise_rationale=f"completeness score {score:.2f} (ratio {ratio:.2f})",
        )


class FormatValidator(BaseValidator):
    """Format: assistant should not be empty; JSON-ish answers keep structure."""

    name = "format"
    version = "1"

    async def assess(self, example: TrainingExample, ctx: ValidatorContext) -> QualityAssessment:
        answer_text = _assistant_text(example)
        reasons: list[str] = []
        if not answer_text.strip():
            score = 0.0
            reasons.append("empty_assistant")
        elif len(answer_text) > 4000:
            score = 0.7
            reasons.append("overlong")
        else:
            score = 1.0
        return QualityAssessment(
            id="",
            example_id=example.id,
            validator_name=self.name,
            validator_version=self.version,
            policy_version=ctx.policy_version,
            status=_status(score),
            verify_state=_verify_state(score, 0.8),
            score=score,
            reason_codes=reasons,
            concise_rationale=f"format score {score:.2f}",
        )


class RefusalValidator(BaseValidator):
    """Refusal handling: a refusal must be unanswerable, not a false refusal."""

    name = "refusal"
    version = "1"

    async def assess(self, example: TrainingExample, ctx: ValidatorContext) -> QualityAssessment:
        answer_text = _assistant_text(example).lower()
        is_refusal = any(
            w in answer_text
            for w in ("cannot answer", "not available", "cannot determine", "unable to")
        )
        # Evidence-scoped (C2): only cited spans determine whether a refusal is
        # false (answerable from evidence) vs legitimate (truly unanswerable).
        cited = [ctx.source_texts[s] for s in example.source_span_ids if s in ctx.source_texts]
        evidence_text = " ".join(cited)
        has_evidence = bool(evidence_text.strip())
        if is_refusal and has_evidence:
            score = 0.3
            reasons = ["false_refusal"]
        elif is_refusal:
            score = 1.0
            reasons = ["legitimate_refusal"]
        else:
            score = 1.0
            reasons = []
        return QualityAssessment(
            id="",
            example_id=example.id,
            validator_name=self.name,
            validator_version=self.version,
            policy_version=ctx.policy_version,
            status=_status(score),
            verify_state=_verify_state(score, 0.8),
            score=score,
            reason_codes=reasons,
            concise_rationale=f"refusal score {score:.2f}",
        )


class SchemaValidator(BaseValidator):
    """C3.1/C4: topology-specific structural validation (fail-closed).

    Enforces the canonical message/role/evidence contract per topology:
    - SFT/KTO message chains start with ``system|user`` and contain an
      assistant turn (mirrors ``GeneratedSFTCandidate`` Pydantic rules);
    - preference pairs each carry an assistant turn;
    - every example cites at least one source span, and every cited span must
      resolve to real evidence (C3.2) — an unresolvable reference is a schema
      failure, never silently ignored;
    - empty required content (user/assistant) reads as a schema failure.
    """

    name = "schema"
    version = "1"

    async def assess(self, example: TrainingExample, ctx: ValidatorContext) -> QualityAssessment:
        reasons: list[str] = []
        score = 1.0

        def _fail(code: str) -> None:
            nonlocal score
            score = min(score, 0.0)
            reasons.append(code)

        if example.topology == Topology.preference:
            all_msgs = (
                list(example.prompt_messages)
                + list(example.chosen_messages)
                + list(example.rejected_messages)
            )
            for m in all_msgs:
                if not m.content.strip():
                    _fail("empty_content")
            if not any(m.role == "assistant" for m in example.chosen_messages):
                _fail("chosen_missing_assistant")
            if not any(m.role == "assistant" for m in example.rejected_messages):
                _fail("rejected_missing_assistant")
        else:
            msgs = list(example.prompt_messages)
            aux = list(example.chosen_messages)
            if not msgs and not aux:
                _fail("no_messages")
            if msgs and msgs[0].role not in ("system", "user"):
                _fail("bad_first_role")
            if not any(m.role == "assistant" for m in aux):
                _fail("missing_assistant")
            for m in msgs + aux:
                if not m.content.strip():
                    _fail("empty_content")

        # evidence resolution (C3.2): each cited span must resolve to real text
        if not example.source_span_ids:
            _fail("no_evidence")
        for sid in example.source_span_ids:
            if sid not in ctx.source_texts:
                _fail("unresolved_evidence")

        return QualityAssessment(
            id="",
            example_id=example.id,
            validator_name=self.name,
            validator_version=self.version,
            policy_version=ctx.policy_version,
            status=_status(score),
            verify_state=_verify_state(score, 0.9),  # C4: schema is a hard floor
            score=score,
            reason_codes=reasons or ["schema_ok"],
            concise_rationale=f"schema score {score:.2f}",
        )


class AnswerabilityValidator(BaseValidator):
    """C3.5/C4: the prompt must be answerable from the cited evidence."""

    name = "answerability"
    version = "1"

    async def assess(self, example: TrainingExample, ctx: ValidatorContext) -> QualityAssessment:
        answer_text = _assistant_text(example).lower()
        cited = [ctx.source_texts[s] for s in example.source_span_ids if s in ctx.source_texts]
        evidence_text = " ".join(cited)
        has_evidence = bool(evidence_text.strip())

        is_refusal = any(
            w in answer_text
            for w in ("cannot answer", "not available", "cannot determine", "unable to")
        )
        reasons: list[str] = []

        if not has_evidence:
            score = 0.0
            reasons.append("no_evidence_for_answer")
        elif is_refusal:
            # a refusal is only legitimate if the cited evidence cannot answer
            # the QUESTION (prompt). Judge answerability from prompt->evidence,
            # not assistant->evidence: a refusal text inherently shares no tokens
            # with the evidence, so grounding the refusal itself is meaningless.
            prompt_answerable = _raw_overlap(_prompt_text(example), evidence_text)
            if prompt_answerable >= 0.2:
                score = 0.3
                reasons.append("false_refusal")
            else:
                score = 1.0
                reasons.append("legitimate_refusal")
        else:
            score = 1.0
            reasons.append("answerable")

        return QualityAssessment(
            id="",
            example_id=example.id,
            validator_name=self.name,
            validator_version=self.version,
            policy_version=ctx.policy_version,
            status=_status(score),
            verify_state=_verify_state(score, 0.8),
            score=score,
            reason_codes=reasons,
            concise_rationale=f"answerability score {score:.2f}",
        )


class SemanticConsistencyValidator(BaseValidator):
    """Semantic consistency (defect 4.1): atomic claims in the assistant
    answer must not contradict the cited evidence — no causal-direction or
    subject/object reversals, no polarity flips, no number/unit mismatches,
    no unsupported entities.

    The deterministic checks (claims.py via semantic.py) originally shipped
    as a library with direct tests but were never wired into this acceptance
    path — the pipeline could still accept a reversed claim. The coverage
    gate exposed the orphans; this validator is the wire-in: every example's
    answer is now claim-checked against its cited evidence, and any
    contradicted claim fails this critical dimension (assemble_decision
    rejects).
    """

    name = "semantic_consistency"
    version = "1"

    def __init__(self) -> None:
        self._verifier = DeterministicSemanticVerifier()

    async def assess(self, example: TrainingExample, ctx: ValidatorContext) -> QualityAssessment:
        answer_text = _assistant_text(example)
        # Evidence-scoped like GroundingValidator: only the spans this example
        # cites may confirm or contradict its claims.
        cited = [ctx.source_texts[s] for s in example.source_span_ids if s in ctx.source_texts]
        evidence_text = " ".join(cited)
        if not evidence_text.strip():
            # mirror GroundingValidator fail-closed: nothing cited = nothing
            # verifiable (grounding independently reports no_cited_evidence)
            score, reasons = 0.0, ["no_cited_evidence"]
        elif not answer_text.strip():
            score, reasons = 0.0, ["empty_answer"]
        else:
            claims = extract_atomic_claims(answer_text)
            claim_assessments = await self._verifier.assess_claims(
                claims, evidence_text, candidate_answer=answer_text
            )
            reasons = sorted(
                {
                    rc
                    for ca in claim_assessments
                    if ca.verdict == ClaimVerdict.contradicted
                    for rc in ca.reason_codes
                }
            )
            score = 0.0 if reasons else 1.0
        return QualityAssessment(
            id="",
            example_id=example.id,
            validator_name=self.name,
            validator_version=self.version,
            policy_version=ctx.policy_version,
            status=_status(score),
            verify_state=_verify_state(score, 0.9),
            score=score,
            reason_codes=reasons,
            concise_rationale=f"semantic_consistency score {score:.2f}",
        )


class PreferenceValidator(BaseValidator):
    """C1/D5: preference-pair quality — a genuine, non-fabricated signal.

    Produces the ``preference_signal`` dimension for preference-topology
    examples. Rejects:
    - identical / near-duplicate chosen and rejected (no signal);
    - pairs trivially separable only by superficial style (verbosity/length);
    - pairs where the chosen lacks minimum absolute quality.
    Fail-closed: returns a low score (review/reject) rather than inventing a
    preference where none exists.
    """

    name = "preference"
    version = "1"

    async def assess(self, example: TrainingExample, ctx: ValidatorContext) -> QualityAssessment:
        from .preference import (
            PreferenceVerdict,
            check_absolute_quality,
            check_preference_signal,
        )

        if example.topology != Topology.preference:
            return QualityAssessment(
                id="",
                example_id=example.id,
                validator_name=self.name,
                validator_version=self.version,
                policy_version=ctx.policy_version,
                status=QualityStatus.review,
                verify_state=Verification.unverified,
                score=0.0,
                reason_codes=["not_preference_topology"],
                concise_rationale="Preference validator only applies to preference topology",
            )

        chosen = "".join(m.content for m in example.chosen_messages if m.role == "assistant")
        rejected = "".join(m.content for m in example.rejected_messages if m.role == "assistant")
        cited = [ctx.source_texts[s] for s in example.source_span_ids if s in ctx.source_texts]
        evidence_text = " ".join(cited)

        reasons: list[str] = []

        # 1. genuine non-duplicate preference signal
        pair = check_preference_signal(chosen, rejected, evidence_text)
        if pair.verdict == PreferenceVerdict.invalid:
            reasons.extend(pair.reason_codes)
            reasons.append("no_preference_signal")
        elif pair.verdict == PreferenceVerdict.review:
            reasons.extend(pair.reason_codes)

        # 2. absolute quality of the chosen
        absq = check_absolute_quality(chosen)
        if absq.verdict == PreferenceVerdict.invalid:
            reasons.extend(absq.reason_codes)

        # 3. superficial style separation must not be the only signal
        if chosen and rejected:
            trivial, _ = preference_is_trivially_separable(chosen, rejected)
            if trivial:
                reasons.append("trivial_style_separation")

        has_fatal = bool(reasons)
        score = 0.0 if has_fatal else 1.0
        if pair.verdict == PreferenceVerdict.review and not has_fatal:
            # marginal signals lower the score to review band but not to reject
            score = 0.6

        return QualityAssessment(
            id="",
            example_id=example.id,
            validator_name=self.name,
            validator_version=self.version,
            policy_version=ctx.policy_version,
            status=_status(score),
            verify_state=_verify_state(score, 0.8),
            score=score,
            reason_codes=reasons or ["preference_signal_ok"],
            concise_rationale=(
                f"preference signal score {score:.2f}: {', '.join(reasons)}"
                if reasons
                else "genuine preference signal present"
            ),
        )


def default_validators() -> list[BaseValidator]:
    """The canonical validator set applied to every example.

    Single source of truth so the product call sites (workspace quality
    report, service pipeline) and the product-path tests cannot drift apart:
    a validator added here runs everywhere, and a test exercising this list
    exercises exactly what production runs.
    """
    return [
        GroundingValidator(),
        CompletenessValidator(),
        FormatValidator(),
        RefusalValidator(),
        SchemaValidator(),
        AnswerabilityValidator(),
        SemanticConsistencyValidator(),
    ]


def assemble_decision(
    assessments: list[QualityAssessment],
    *,
    example_id: str,
    is_preference: bool = False,
    policy: AcceptancePolicy | None = None,
) -> QualityAssessment:
    """Fold per-validator assessments into one overall assessment (C4).

    Applies hard floors plus three-state verification, fail-closed:
    - critical dimensions (grounding, schema, answerability, instruction
      fulfilment) must be ``verified`` for acceptance;
    - any critical dimension left ``unverified`` (never assessed) forces
      ``review`` — absence of evidence is never certification;
    - any critical dimension ``failed`` (assessed below its floor) forces
      ``rejected``;
    - non-critical dimensions fold into the overall score used by the
      acceptance ceiling.
    """
    policy = policy or AcceptancePolicy()
    verify: dict[str, Verification] = {a.validator_name: a.verify_state for a in assessments}
    dims = {a.validator_name: a.score for a in assessments}

    # instruction fulfilment is the contract's policy dimension; the completeness
    # validator is its provider unless a dedicated one is present (fail-closed:
    # if neither dimension was assessed, policy sees 0.0 and rejects).
    if "instruction_fulfillment" not in dims and "completeness" in dims:
        dims["instruction_fulfillment"] = dims["completeness"]
        verify["instruction_fulfillment"] = verify.get("completeness", Verification.unverified)
    if is_preference and "preference_signal" not in dims:
        # Defect 4.2 FIX: missing preference signal must result in UNVERIFIED,
        # never fabricated as 1.0/verified. The correct behavior is to let the
        # preference validator produce its own dimension, or leave it unverified
        # so the caller can quarantine/review. Rather than fabricate, add
        # "preference_signal" with 0.0 and unverified to signal that preference
        # evaluation was never performed.
        dims["preference_signal"] = 0.0
        verify["preference_signal"] = Verification.unverified

    # C4 critical dimensions that must be verified to accept. ``present`` is the
    # set of dimension keys actually certified (after the completeness ->
    # instruction_fulfillment alias above); a dimension that was never produced
    # OR returned unverified is not certifiable (fail-closed).
    # semantic_consistency is critical (defect 4.1): a claim that reverses or
    # contradicts its cited evidence must force rejection, not just lower the
    # average.
    critical = [
        "grounding",
        "schema",
        "answerability",
        "instruction_fulfillment",
        "semantic_consistency",
    ]
    present = set(verify.keys())
    failed_critical = [d for d in critical if d in present and verify.get(d) == Verification.failed]
    unverified_critical = [
        d for d in critical if d not in present or verify.get(d) == Verification.unverified
    ]
    certifiable = not failed_critical and not unverified_critical

    overall = sum(dims.values()) / max(len(dims), 1)
    dims["overall"] = round(overall, 4)
    over_ceiling, reasons, status = policy.assess(dims, is_preference=is_preference)

    if failed_critical:
        status = QualityStatus.rejected
        reasons = reasons + [f"critical_failed:{d}" for d in failed_critical]
    elif not certifiable:
        # a critical dimension was never certified (unverified or missing)
        status = QualityStatus.review
        reasons = reasons + [f"critical_unverified:{d}" for d in unverified_critical]
    elif over_ceiling:
        status = QualityStatus.accepted
    else:
        status = QualityStatus.review

    reason = _aggregate_reasons(assessments, status) + reasons
    per_validator = {a.validator_name: a.score for a in assessments}
    return QualityAssessment(
        id="",
        example_id=example_id,
        validator_name="overall",
        validator_version="1",
        policy_version="1",
        status=status,
        verify_state=(
            Verification.verified if status == QualityStatus.accepted else Verification.failed
        ),
        score=round(overall, 4),
        reason_codes=reason,
        concise_rationale="overall acceptance assessment",
        evidence={
            "per_validator": per_validator,
            "accepted": status == QualityStatus.accepted,
            "reasons": reasons,
            "verify": verify,
            "certifiable": certifiable,
        },
    )


def _aggregate_reasons(assessments: list[QualityAssessment], status: QualityStatus) -> list[str]:
    codes: list[str] = [status.value]
    for a in assessments:
        if a.status != QualityStatus.accepted:
            codes.extend(a.reason_codes)
    seen: list[str] = []
    for c in codes:
        if c not in seen:
            seen.append(c)
    return seen


def _assistant_text(example: TrainingExample) -> str:
    msgs = example.chosen_messages or example.prompt_messages
    for m in msgs:
        if m.role == "assistant":
            return m.content
    return ""


def _prompt_text(example: TrainingExample) -> str:
    parts: list[str] = []
    for m in example.prompt_messages + example.chosen_messages + example.rejected_messages:
        if m.role in ("user", "system"):
            parts.append(m.content)
    return " ".join(parts)


_STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "of",
    "to",
    "in",
    "on",
    "for",
    "with",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "by",
    "as",
    "at",
    "from",
    "it",
    "this",
    "that",
    "according",
    "provided",
    "material",
    "based",
    "following",
    "key",
    "about",
    "you",
    "your",
    "would",
    "should",
    "could",
    "will",
    "can",
    "not",
    "no",
    "any",
    "please",
    "answer",
    "question",
    "source",
}


def _fractional_overlap(answer: str, evidence: str) -> tuple[float, list[str]]:
    """Fraction of CONTENT answer tokens found in evidence (stopwords excluded).

    Tokens are stripped of non-alphanumeric characters before comparison so
    punctuation on the same word (``material:``, ``source.``) does not defeat
    stopword filtering or evidence matching.

    Fail-closed (§C): grounding must be near-complete. Any substantive answer
    token that is not backed by the cited evidence reflects a potential
    fabrication or substitution (e.g. a wrong number / swapped key term).
    Underscore the shortfall so partial coverage does not read as "grounded".
    """
    from ...domain.hashing import normalize_text

    def _lexical(text: str) -> set[str]:
        return {_strip_non_alpha(t) for t in normalize_text(text).split() if _strip_non_alpha(t)}

    ans_tokens = {t for t in _lexical(answer) if t not in _STOPWORDS}
    ev_tokens = _lexical(evidence)
    if not ans_tokens:
        return (0.0, ["empty_answer"])
    if not ev_tokens:
        return (0.0, ["no_evidence"])
    overlap = len(ans_tokens & ev_tokens) / len(ans_tokens)
    # amplify ungrounded content: score falls quickly as coverage drops
    ungrounded = 1.0 - overlap
    score = max(0.0, 1.0 - 2.0 * ungrounded)
    reasons = ["low_grounding"] if score < 0.6 else []
    return (score, reasons)


def _strip_non_alpha(token: str) -> str:
    return "".join(ch for ch in token if ch.isalnum())


def _raw_overlap(answer: str, evidence: str) -> float:
    """Raw fraction of CONTENT answer tokens found in evidence (0..1).

    Unlike :func:`_fractional_overlap` (which returns an amplified, fail-closed
    score), this returns the plain coverage fraction — used where the signal is
    merely 'does the evidence touch the topic' (e.g. answerability), not a
    point-blank grounding verdict.
    """
    from ...domain.hashing import normalize_text

    def _lex(t: str) -> set[str]:
        return {_strip_non_alpha(x) for x in normalize_text(t).split() if _strip_non_alpha(x)}

    a = {t for t in _lex(answer) if t not in _STOPWORDS}
    e = _lex(evidence)
    if not a or not e:
        return 0.0
    return len(a & e) / len(a)
