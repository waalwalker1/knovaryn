"""Quality validation framework (spec §13, §14).

Validators turn a training example + its supporting evidence into a
:class:`QualityAssessment`. Each validator is versioned and returns a score
plus reason codes. The framework folds per-validator results into an overall
accept/review/reject decision using :class:`AcceptancePolicy`.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from ...domain.schemas import QualityAssessment, QualityStatus, TrainingExample
from ...domain.policies import AcceptancePolicy


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


class GroundingValidator(BaseValidator):
    """Faithfulness: the assistant answer must be traceable to the evidence."""

    name = "grounding"
    version = "1"

    async def assess(self, example: TrainingExample, ctx: ValidatorContext) -> QualityAssessment:
        answer_text = _assistant_text(example)
        evidence_text = " ".join(ctx.source_texts.values())
        score, reasons = _fractional_overlap(answer_text, evidence_text)
        return QualityAssessment(
            id="",
            example_id=example.id,
            validator_name=self.name,
            validator_version=self.version,
            policy_version=ctx.policy_version,
            status=_status(score),
            score=score,
            reason_codes=reasons + (["no_evidence"] if not evidence_text.strip() else []),
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
        is_refusal = any(w in answer_text for w in ("cannot answer", "not available", "cannot determine", "unable to"))
        evidence_text = " ".join(ctx.source_texts.values())
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
            score=score,
            reason_codes=reasons,
            concise_rationale=f"refusal score {score:.2f}",
        )


def assemble_decision(
    assessments: list[QualityAssessment],
    *,
    example_id: str,
    is_preference: bool = False,
    policy: AcceptancePolicy | None = None,
) -> QualityAssessment:
    """Fold per-validator assessments into one overall assessment."""
    policy = policy or AcceptancePolicy()
    dims = {a.validator_name: a.score for a in assessments}
    dims["overall"] = sum(dims.values()) / max(len(dims), 1)
    if is_preference and "preference_signal" not in dims:
        dims["preference_signal"] = 1.0
    accepted, reasons, status = policy.assess(dims, is_preference=is_preference)
    reason = _aggregate_reasons(assessments, status) + reasons
    return QualityAssessment(
        id="",
        example_id=example_id,
        validator_name="overall",
        validator_version="1",
        policy_version="1",
        status=status if not accepted else QualityStatus.accepted,
        score=round(dims["overall"], 4),
        reason_codes=reason,
        concise_rationale="overall acceptance assessment",
        evidence={
            "per_validator": {a.validator_name: a.score for a in assessments},
            "accepted": accepted,
            "reasons": reasons,
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
    "a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "been", "by", "as", "at", "from", "it",
    "this", "that", "according", "provided", "material", "based", "following",
    "key", "about", "you", "your", "would", "should", "could", "will", "can",
    "not", "no", "any", "please", "answer", "question", "source",
}


def _fractional_overlap(answer: str, evidence: str) -> tuple[float, list[str]]:
    """Fraction of CONTENT answer tokens found in evidence (stopwords excluded).

    Tokens are stripped of non-alphanumeric characters before comparison so
    punctuation on the same word (``material:``, ``source.``) does not defeat
    stopword filtering or evidence matching.
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
    reasons = ["low_grounding"] if overlap < 0.6 else []
    return (overlap, reasons)


def _strip_non_alpha(token: str) -> str:
    return "".join(ch for ch in token if ch.isalnum())
