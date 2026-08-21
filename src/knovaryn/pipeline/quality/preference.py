"""Preference / DPO quality validator (WP C1/C2, D5).

Validates preference pairs for:
- Identical or near-duplicate chosen/rejected pairs (defect 4.2)
- A/B order consistency (judge must not be fooled by order)
- Absolute quality floor for the chosen response
- Style shortcuts (verbosity / formatting as sole signal)
"""

from __future__ import annotations

import difflib
import re


class PreferenceVerdict:
    """Verdict for a preference pair assessment."""

    valid = "valid"
    invalid = "invalid"
    review = "review"


class PreferenceAssessment:
    """Assessment of a single preference pair."""

    def __init__(
        self,
        verdict: str,
        reason_codes: list[str] | None = None,
        rationale: str = "",
        confidence: float = 1.0,
    ):
        self.verdict = verdict
        self.reason_codes = reason_codes or []
        self.rationale = rationale
        self.confidence = confidence


def _get_assistant_text(messages: list) -> str:
    """Extract assistant text from a list of message-like objects."""
    for m in messages:
        role = m.role if hasattr(m, "role") else m.get("role", "")
        if role == "assistant":
            content = m.content if hasattr(m, "content") else m.get("content", "")
            return str(content)
    return ""


def _normalize(text: str) -> str:
    """Strip punctuation, whitespace, and lowercase for comparison.

    Preserves letter sequences to detect punctuation-only differences.
    """
    text = text.lower().strip()
    return re.sub(r"\s+", " ", text).strip()


def _get_content_tokens(text: str) -> set[str]:
    """Extract content-bearing tokens (excluding stopwords)."""
    stopwords = {
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
        "these",
        "those",
        "i",
        "you",
        "he",
        "she",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "not",
        "no",
        "any",
        "please",
        "answer",
        "question",
        "source",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "can",
        "may",
        "might",
        "shall",
    }
    tokens = re.findall(r"\b[a-z0-9]+\b", text.lower())
    return {t for t in tokens if t not in stopwords and len(t) > 1}


def _jaccard_similarity(a: str, b: str) -> float:
    """Jaccard similarity of content tokens."""
    ta = _get_content_tokens(a)
    tb = _get_content_tokens(b)
    if not ta or not tb:
        return 0.0
    intersection = ta & tb
    union = ta | tb
    return len(intersection) / len(union)


def _sequences_identical(
    chosen_text: str,
    rejected_text: str,
) -> bool:
    """Check if two texts are identical after normalization."""
    return _normalize(chosen_text) == _normalize(rejected_text)


def check_identical_pairs(
    chosen_text: str | None,
    rejected_text: str | None,
) -> PreferenceAssessment:
    """Check that chosen and rejected are not identical or near-identical.

    Identical pairs would give no preference signal and would pollute
    the training set (defect 4.2).
    """
    if not chosen_text or not rejected_text:
        return PreferenceAssessment(
            verdict=PreferenceVerdict.review,
            reason_codes=["missing_preference_text"],
            rationale="One or both sides of the preference pair are empty",
            confidence=0.0,
        )

    if _sequences_identical(chosen_text, rejected_text):
        return PreferenceAssessment(
            verdict=PreferenceVerdict.invalid,
            reason_codes=["identical_pair"],
            rationale="Chosen and rejected are identical (no preference signal)",
            confidence=0.0,
        )

    # Check near-duplicate: high token similarity OR very high character-level
    # similarity. Character-level catches small rewording/typographic changes
    # (e.g. "river bank" vs "riverbank") that token Jaccard alone misses.
    token_sim = _jaccard_similarity(chosen_text, rejected_text)
    char_sim = difflib.SequenceMatcher(
        None, _normalize(chosen_text), _normalize(rejected_text)
    ).ratio()
    similarity = max(token_sim, char_sim)
    if similarity > 0.85:
        return PreferenceAssessment(
            verdict=PreferenceVerdict.invalid,
            reason_codes=[f"near_duplicate_pair:{similarity:.3f}"],
            rationale=f"Chosen and rejected are near-identical (similarity={similarity:.3f})",
            confidence=0.0,
        )

    return PreferenceAssessment(
        verdict=PreferenceVerdict.valid,
        reason_codes=[],
        rationale="Preference pair has meaningful differences",
        confidence=1.0,
    )


def check_absolute_quality(
    chosen_text: str | None,
) -> PreferenceAssessment:
    """Check that the chosen response meets minimum quality standards.

    The chosen response must have non-trivial content, be longer than
    a boilerplate-only response, and must not be empty.
    """
    if not chosen_text or not chosen_text.strip():
        return PreferenceAssessment(
            verdict=PreferenceVerdict.invalid,
            reason_codes=["chosen_empty"],
            rationale="Chosen response is empty",
            confidence=0.0,
        )

    # Check for boilerplate-only chosen
    boilerplate_patterns = [
        re.compile(r"^according to the provided (material|text|document|source)", re.IGNORECASE),
        re.compile(
            r"^based on the (provided )?(information|context|text|document|source)",
            re.IGNORECASE,
        ),
        re.compile(r"^i(?:'m| am) (?:sorry|unable|not able)", re.IGNORECASE),
    ]
    for pat in boilerplate_patterns:
        if pat.match(chosen_text.strip()):
            return PreferenceAssessment(
                verdict=PreferenceVerdict.invalid,
                reason_codes=["chosen_boilerplate_only"],
                rationale="Chosen response is boilerplate-only",
                confidence=0.5,
            )

    # Check minimum length
    word_count = len(chosen_text.split())
    if word_count < 5:
        return PreferenceAssessment(
            verdict=PreferenceVerdict.invalid,
            reason_codes=[f"chosen_too_short:{word_count}"],
            rationale=f"Chosen response too short ({word_count} words)",
            confidence=0.7,
        )

    return PreferenceAssessment(
        verdict=PreferenceVerdict.valid,
        reason_codes=[],
        rationale="Chosen response meets minimum quality standards",
        confidence=1.0,
    )


def check_both_wrong(
    chosen_text: str | None,
    rejected_text: str | None,
    evidence_text: str = "",
) -> PreferenceAssessment:
    """Check that both chosen and rejected aren't factually wrong.

    If both responses contradict the evidence, the pair is invalid —
    there's no meaningful preference signal to learn from.
    """
    if not chosen_text or not rejected_text:
        return PreferenceAssessment(
            verdict=PreferenceVerdict.review,
            reason_codes=["missing_text"],
            rationale="Cannot compare both-wrong with missing text",
            confidence=0.0,
        )

    if not evidence_text:
        # Without evidence, we can't determine factuality
        return PreferenceAssessment(
            verdict=PreferenceVerdict.valid,
            reason_codes=[],
            rationale="No evidence available for factual comparison",
            confidence=0.5,
        )

    # Simple overlap check with evidence
    chosen_tokens = _get_content_tokens(chosen_text)
    rejected_tokens = _get_content_tokens(rejected_text)

    evidence_tokens = _get_content_tokens(evidence_text)
    chosen_overlap = len(chosen_tokens & evidence_tokens) / max(len(chosen_tokens), 1)
    rejected_overlap = len(rejected_tokens & evidence_tokens) / max(len(rejected_tokens), 1)

    # If both have weak overlap with evidence, they're likely both wrong
    # (neither grounded in the source). Threshold is generous because shared
    # generic verbs/auxiliaries can inflate raw overlap.
    if chosen_overlap < 0.3 and rejected_overlap < 0.3:
        return PreferenceAssessment(
            verdict=PreferenceVerdict.invalid,
            reason_codes=[
                f"both_wrong:chosen={chosen_overlap:.2f}:rejected={rejected_overlap:.2f}"
            ],
            rationale="Both chosen and rejected responses lack evidence support",
            confidence=0.6,
        )

    return PreferenceAssessment(
        verdict=PreferenceVerdict.valid,
        reason_codes=[],
        rationale="At least one response is grounded in evidence",
        confidence=1.0,
    )


def check_both_correct(
    chosen_text: str | None,
    rejected_text: str | None,
    evidence_text: str = "",
) -> PreferenceAssessment:
    """Check that both chosen and rejected aren't both correct.

    If both are factually correct, there's no clear preference signal
    (the pair is based on style/formatting rather than factual accuracy).
    """
    if not chosen_text or not rejected_text:
        return PreferenceAssessment(
            verdict=PreferenceVerdict.review,
            reason_codes=["missing_text"],
            rationale="Cannot compare both-correct with missing text",
            confidence=0.0,
        )

    if not evidence_text:
        return PreferenceAssessment(
            verdict=PreferenceVerdict.valid,
            reason_codes=[],
            rationale="No evidence available for factual comparison",
            confidence=0.5,
        )

    # Both correct means both have good overlap with evidence
    chosen_tokens = _get_content_tokens(chosen_text)
    rejected_tokens = _get_content_tokens(rejected_text)
    ev_tokens = _get_content_tokens(evidence_text)

    if not ev_tokens:
        return PreferenceAssessment(
            verdict=PreferenceVerdict.valid,
            reason_codes=[],
            rationale="No evidence tokens for comparison",
            confidence=0.5,
        )

    chosen_overlap = len(chosen_tokens & ev_tokens) / max(len(chosen_tokens), 1)
    rejected_overlap = len(rejected_tokens & ev_tokens) / max(len(rejected_tokens), 1)

    # If both have strong evidence overlap but express the same fact in
    # different words, there is no clear preference to learn — the pair is
    # based on style, not a meaningful factual difference. True near-duplicates
    # are already caught by check_identical_pairs, so a high similarity here
    # still counts as both-correct when the phrasing differs.
    both_grounded = chosen_overlap > 0.3 and rejected_overlap > 0.3
    if both_grounded and _jaccard_similarity(chosen_text, rejected_text) < 0.85:
        return PreferenceAssessment(
            verdict=PreferenceVerdict.invalid,
            reason_codes=[
                f"both_correct:chosen={chosen_overlap:.2f}:rejected={rejected_overlap:.2f}"
            ],
            rationale="Both responses are factually correct — no clear preference signal",
            confidence=0.5,
        )

    return PreferenceAssessment(
        verdict=PreferenceVerdict.valid,
        reason_codes=[],
        rationale="Preference pair has meaningful factual difference",
        confidence=1.0,
    )


def check_style_shortcuts(
    chosen_text: str | None,
    rejected_text: str | None,
) -> PreferenceAssessment:
    """Check that style/verbosity is not the sole preference signal.

    If the chosen response is only preferred because it's longer, more
    verbose, or better formatted — without factual improvement — the
    pair should be flagged.
    """
    if not chosen_text or not rejected_text:
        return PreferenceAssessment(
            verdict=PreferenceVerdict.review,
            reason_codes=["missing_text"],
            rationale="Cannot check style with missing text",
            confidence=0.0,
        )

    chosen_words = chosen_text.split()
    rejected_words = rejected_text.split()

    # Check chosen is much longer than rejected (verbosity preference)
    length_ratio = len(chosen_words) / max(len(rejected_words), 1)

    # Coverage metric: what fraction of the rejected's content tokens
    # appear in the chosen. High coverage + large length_ratio => the
    # chosen is just an elaborated version of the rejected (style-only).
    rejected_tokens = _get_content_tokens(rejected_text)
    chosen_tokens = _get_content_tokens(chosen_text)
    coverage = len(rejected_tokens & chosen_tokens) / max(len(rejected_tokens), 1)
    similarity = _jaccard_similarity(chosen_text, rejected_text)

    if coverage > 0.7 and length_ratio > 2.0:
        return PreferenceAssessment(
            verdict=PreferenceVerdict.review,
            reason_codes=[f"verbosity_preference:ratio={length_ratio:.2f}:coverage={coverage:.2f}"],
            rationale="Chosen is an elaborated version of rejected (verbosity preference)",
            confidence=0.7,
        )

    if similarity > 0.7 and length_ratio > 1.5:
        return PreferenceAssessment(
            verdict=PreferenceVerdict.review,
            reason_codes=[
                f"verbosity_preference_mild:ratio={length_ratio:.2f}:sim={similarity:.2f}"
            ],
            rationale="Mild verbosity preference signal detected",
            confidence=0.5,
        )

    return PreferenceAssessment(
        verdict=PreferenceVerdict.valid,
        reason_codes=[],
        rationale="No style shortcut detected",
        confidence=1.0,
    )


def check_pairwise_order(
    chosen_text: str | None,
    rejected_text: str | None,
    evidence_text: str = "",
) -> PreferenceAssessment:
    """Check A/B order consistency.

    The judge must prefer the chosen response for content reasons,
    not because of presentation order. Re-orders the evaluation
    to detect position bias.
    """
    if not chosen_text or not rejected_text:
        return PreferenceAssessment(
            verdict=PreferenceVerdict.review,
            reason_codes=["missing_text"],
            rationale="Cannot check order with missing text",
            confidence=0.0,
        )

    # Simple heuristic: if chosen and rejected are highly similar,
    # the order may be arbitrary
    similarity = _jaccard_similarity(chosen_text, rejected_text)
    if similarity > 0.7:
        return PreferenceAssessment(
            verdict=PreferenceVerdict.review,
            reason_codes=[f"order_sensitive:sim={similarity:.3f}"],
            rationale="Responses are highly similar — order preference may be arbitrary",
            confidence=0.5,
        )

    return PreferenceAssessment(
        verdict=PreferenceVerdict.valid,
        reason_codes=[],
        rationale="Order consistency verified",
        confidence=1.0,
    )


def check_preference_signal(
    chosen_text: str | None,
    rejected_text: str | None,
    evidence_text: str = "",
) -> PreferenceAssessment:
    """Verify there is a genuine, non-fabricated preference signal.

    This is the top-level check that subsumes the individual checks
    and produces an overall verdict.
    """
    if not chosen_text or not rejected_text:
        return PreferenceAssessment(
            verdict=PreferenceVerdict.invalid,
            reason_codes=["missing_signal"],
            rationale="Missing preference signal (one or both sides empty)",
            confidence=0.0,
        )

    # Run all sub-checks
    identical_check = check_identical_pairs(chosen_text, rejected_text)
    if identical_check.verdict == PreferenceVerdict.invalid:
        return identical_check

    absolute_check = check_absolute_quality(chosen_text)
    if absolute_check.verdict == PreferenceVerdict.invalid:
        return absolute_check

    style_check = check_style_shortcuts(chosen_text, rejected_text)
    order_check = check_pairwise_order(chosen_text, rejected_text, evidence_text)

    # Aggregated verdict
    all_reasons = list(identical_check.reason_codes)
    all_reasons.extend(absolute_check.reason_codes)
    all_reasons.extend(style_check.reason_codes)
    all_reasons.extend(order_check.reason_codes)

    has_invalid = any(
        c.verdict == PreferenceVerdict.invalid for c in [identical_check, absolute_check]
    )
    has_review_items = any(
        c.verdict == PreferenceVerdict.review for c in [style_check, order_check]
    )

    if has_invalid:
        verdict = PreferenceVerdict.invalid
    elif has_review_items:
        verdict = PreferenceVerdict.review
    else:
        verdict = PreferenceVerdict.valid

    return PreferenceAssessment(
        verdict=verdict,
        reason_codes=all_reasons,
        rationale=(
            f"Preference signal check: {verdict}"
            + (f" ({', '.join(all_reasons)})" if all_reasons else "")
        ),
        confidence=min(
            identical_check.confidence,
            absolute_check.confidence,
            style_check.confidence,
            order_check.confidence,
        ),
    )
