"""Information gain validator (WP C1/C2).

Detects low-information or trivial answers: heading echoes, prompt echoes,
circular reasoning, boilerplate-only responses, etc.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class InformationGainResult:
    """Result of an information gain check."""

    score: float  # 0.0 = no gain, 1.0 = full gain
    reason_codes: list[str] = field(default_factory=list)
    concise_rationale: str = ""
    novel_content_tokens: int = 0
    repetition_ratio: float = 0.0
    prompt_similarity: float = 0.0
    heading_similarity: float = 0.0


# Phrase boilerplate patterns
BOILERPLATE_PATTERNS: list[re.Pattern] = [
    re.compile(r"according to the provided (material|text|document|source)", re.IGNORECASE),
    re.compile(
        r"based on the (provided )?(information|context|text|document|source)", re.IGNORECASE
    ),
    re.compile(r"as per the (provided )?(information|text|document)", re.IGNORECASE),
    re.compile(
        r"the (provided )?(material|text|document|source|context|information) "
        r"(states|mentions|indicates|says|provides|notes)",
        re.IGNORECASE,
    ),
    re.compile(r"in the (provided )?(material|text|document|source|context)", re.IGNORECASE),
]

# Only disclaimer / refusal patterns
DISCLAIMER_ONLY: list[re.Pattern] = [
    re.compile(r"^i(?:'m| am) (?:sorry|unable|not able|not equipped|not designed)", re.IGNORECASE),
    re.compile(r"^as an ai (?:assistant|language model)", re.IGNORECASE),
    re.compile(r"^i cannot (?:answer|provide|help|respond)", re.IGNORECASE),
    re.compile(r"^(?:i'm )?not (?:sure|certain|able)", re.IGNORECASE),
]


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens."""
    return re.findall(r"\b[a-z0-9]+\b", text.lower())


def _strip_boilerplate(text: str) -> str:
    """Remove common boilerplate prefix phrases."""
    result = text
    for pattern in BOILERPLATE_PATTERNS:
        result = pattern.sub("", result)
    return result.strip()


def _normalized_similarity(a: str, b: str) -> float:
    """Jaccard similarity of content tokens between two strings."""
    a_tokens = set(_tokenize(a))
    b_tokens = set(_tokenize(b))
    # Remove stopwords
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
        "according",
        "provided",
        "material",
        "based",
        "following",
        "key",
        "about",
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
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "being",
    }
    a_clean = {t for t in a_tokens if t not in stopwords}
    b_clean = {t for t in b_tokens if t not in stopwords}
    if not a_clean or not b_clean:
        return 0.0
    intersection = a_clean & b_clean
    union = a_clean | b_clean
    return len(intersection) / len(union)


def assess_information_gain(
    answer: str,
    prompt: str = "",
    heading: str = "",
    task_type: str = "factual_explanation",
) -> InformationGainResult:
    """Assess information gain of an answer relative to prompt/heading.

    Args:
        answer: The candidate answer text.
        prompt: The user/system prompt.
        heading: The section/chunk heading, if any.
        task_type: Type of task ('factual_explanation', 'procedure', 'comparison',
                  'summarization', 'extraction', 'tool_use', 'refusal',
                  'evaluation_question').

    Returns:
        InformationGainResult with score and reason codes.
    """
    reason_codes: list[str] = []
    answer_stripped = answer.strip()
    heading_stripped = heading.strip()

    if not answer_stripped:
        return InformationGainResult(
            score=0.0,
            reason_codes=["empty_answer"],
            concise_rationale="Answer is empty",
        )

    # Token-level analysis
    answer_tokens = _tokenize(answer_stripped)
    unique_tokens = set(answer_tokens)
    total_tokens = len(answer_tokens)
    unique_ratio = len(unique_tokens) / max(total_tokens, 1)

    # Check for disclaimer-only response
    for pattern in DISCLAIMER_ONLY:
        if pattern.match(answer_stripped):
            return InformationGainResult(
                score=0.0,
                reason_codes=["disclaimer_only"],
                concise_rationale="Response contains only disclaimer without substantive content",
            )

    # Check repetition ratio
    if total_tokens > 0:
        # Count repeated n-grams (bigrams)
        bigrams_raw = [
            answer_tokens[i] + " " + answer_tokens[i + 1] for i in range(total_tokens - 1)
        ]
        bigram_set = set(bigrams_raw)
        repetition_ratio = 1.0 - (len(bigram_set) / max(len(bigrams_raw), 1))
        if repetition_ratio > 0.85:
            reason_codes.append(f"high_repetition:{repetition_ratio:.2f}")
    else:
        repetition_ratio = 0.0

    # Check heading similarity
    heading_similarity = 0.0
    if heading_stripped:
        heading_similarity = _normalized_similarity(answer_stripped, heading_stripped)
        if heading_similarity > 0.85:
            reason_codes.append(f"heading_echo:{heading_similarity:.2f}")

    # Check prompt similarity
    prompt_similarity = 0.0
    if prompt:
        prompt_similarity = _normalized_similarity(answer_stripped, prompt)
        if prompt_similarity > 0.85:
            reason_codes.append(f"prompt_echo:{prompt_similarity:.2f}")

    # Check for boilerplate-only content
    stripped_answer = _strip_boilerplate(answer_stripped)
    if not stripped_answer.strip():
        reason_codes.append("boilerplate_only")
    else:
        # Detect answers dominated by boilerplate markers even when a little
        # filler remains (e.g. "the information states the following key points").
        # If removing all boilerplate phrases leaves only generic framing words,
        # the answer carries no real information.
        BOILERPLATE_LEADING = {
            "the",
            "information",
            "material",
            "text",
            "document",
            "source",
            "context",
            "states",
            "mentions",
            "indicates",
            "says",
            "provides",
            "notes",
            "following",
            "key",
            "points",
            "above",
            "based",
            "provided",
            "according",
            "per",
            "as",
            "that",
            "this",
            "these",
            "those",
            "it",
            "and",
            "but",
            "or",
            "of",
            "in",
            "on",
            "for",
            "with",
            "is",
            "are",
            "was",
            "were",
            "a",
            "an",
        }
        residual_tokens = set(_tokenize(stripped_answer))
        content_tokens = residual_tokens - BOILERPLATE_LEADING
        if not content_tokens:
            reason_codes.append("boilerplate_only")

    # Check for circular answer (answer that restates the question without adding info)
    question_words = {
        "what",
        "why",
        "how",
        "when",
        "where",
        "who",
        "which",
        "does",
        "is",
        "are",
        "can",
    }
    if any(answer_stripped.lower().startswith(w + " ") for w in question_words):
        # Answer starts like a question — possible circular
        pass  # Not always circular; check further

    # Check for extremely low unique token ratio
    if total_tokens >= 5 and unique_ratio < 0.3:
        reason_codes.append(f"low_unique_token_ratio:{unique_ratio:.2f}")

    # Circular / self-referential reasoning: the answer restates the question's
    # own meta-terms ("the question", "the answer", "what it asks") without adding
    # any domain content. Detect when metalinguistic words dominate the tokens.
    METALINGUISTIC = {
        "answer",
        "question",
        "what",
        "meaning",
        "asks",
        "ask",
        "asked",
        "about",
        "refers",
        "refer",
        "regarding",
        "concerning",
        "itself",
        "statement",
        "phrase",
        "word",
        "words",
        "sentence",
        "described",
    }
    meta_tokens = [t for t in answer_tokens if t in METALINGUISTIC]
    if total_tokens >= 8 and len(meta_tokens) / total_tokens > 0.35:
        reason_codes.append(f"circular_reasoning:{len(meta_tokens) / total_tokens:.2f}")

    # Task-specific checks
    if task_type == "factual_explanation" and not reason_codes:
        # Must have at least one predicate/claim beyond boilerplate
        content = stripped_answer if stripped_answer else answer_stripped
        has_predicate = len(_tokenize(content)) >= 5
        if not has_predicate:
            reason_codes.append("insufficient_content_for_explanation")

    elif task_type == "comparison" and not reason_codes:
        # A comparison answer must do more than list items joined by "and".
        # Look for comparative/contrastive markers that signal a real dimension
        # is weighed. Generic "and" does not constitute a comparison.
        comparison_markers = [
            " but ",
            " while ",
            " whereas ",
            " however ",
            " compared ",
            " unlike ",
            " greater ",
            " less ",
            " better ",
            " worse ",
            " faster ",
            " slower ",
            " higher ",
            " lower ",
            " more ",
            " fewer ",
            " superior ",
            " inferior ",
            " difference ",
            "than",
            "advantage",
            "disadvantage",
            "pros",
            "cons",
        ]
        if not any(m in answer_stripped.lower() for m in comparison_markers):
            reason_codes.append("missing_comparison_dimension")

    elif task_type == "summarization" and not reason_codes:
        # Summarization must be shorter than the prompt (reasonable)
        if len(_tokenize(answer_stripped)) > len(_tokenize(prompt)) * 1.2:
            reason_codes.append("summary_not_condensed")

    elif task_type == "extraction":
        # Extraction may be concise — check requested fields exist
        pass  # Task-specific field checking done elsewhere

    # Compute final score
    if reason_codes:
        # Score proportional to severity
        severity_map = {
            "heading_echo": 0.0,
            "prompt_echo": 0.0,
            "boilerplate_only": 0.0,
            "high_repetition": 0.1,
            "low_unique_token_ratio": 0.2,
            "insufficient_content_for_explanation": 0.0,
            "missing_comparison_dimension": 0.3,
            "summary_not_condensed": 0.5,
            "disclaimer_only": 0.0,
            "empty_answer": 0.0,
            "circular_reasoning": 0.0,
        }
        worst_severity = 1.0
        for code in reason_codes:
            base_code = code.split(":")[0]
            severity = severity_map.get(base_code, 0.5)
            worst_severity = min(worst_severity, severity)
        score = worst_severity
    else:
        score = 1.0

    return InformationGainResult(
        score=score,
        reason_codes=reason_codes,
        concise_rationale=(
            f"information gain score {score:.2f}: {', '.join(reason_codes)}"
            if reason_codes
            else "adequate information gain"
        ),
        novel_content_tokens=len(unique_tokens),
        repetition_ratio=repetition_ratio,
        prompt_similarity=prompt_similarity,
        heading_similarity=heading_similarity,
    )
