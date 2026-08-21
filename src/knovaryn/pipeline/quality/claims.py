"""Atomic claim model for semantic factuality analysis (WP A1/A2).

Defines typed schemas for extracting and representing atomic factual claims
from evidence text, enabling deterministic and model-based verification.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ClaimVerdict(StrEnum):
    """Verdict for a single atomic claim against cited evidence."""

    entailed = "entailed"
    contradicted = "contradicted"
    insufficient = "insufficient"
    unverified = "unverified"


class NormalizedNumber(BaseModel):
    """A normalized number extracted from text, with context."""

    raw: str
    value: float
    unit: str = ""
    prefix: str = ""  # currency symbol, approximate marker, etc.
    is_range: bool = False
    range_start: float | None = None
    range_end: float | None = None
    is_percentage: bool = False
    percentage_value: float | None = None
    confidence: float = 1.0


class NormalizedDate(BaseModel):
    """A normalized date extracted from text."""

    raw: str
    iso_date: str = ""  # YYYY-MM-DD when fully resolvable
    year: int | None = None
    month: int | None = None
    day: int | None = None
    is_relative: bool = False
    relative_anchor: str = ""
    confidence: float = 1.0


class NormalizedUnit(BaseModel):
    """A unit of measurement with normalized form."""

    raw: str
    canonical: str  # "seconds", "minutes", "bytes", "megabytes", etc.
    unit_type: str = ""  # "time", "data", "distance", "currency", "percentage", etc.
    is_compound: bool = False
    multiplier_to_base: float = 1.0  # multiply by this to get base unit value
    confidence: float = 1.0


class AtomicClaim(BaseModel):
    """A single atomic factual claim extracted from text.

    Represents one proposition: subject + relation + object + modifiers.
    """

    text: str
    subject: str | None = None
    relation: str | None = None
    obj: str | None = Field(default=None, alias="object")
    polarity: Literal["affirmed", "negated", "unknown"] = "affirmed"
    # proposition, comparison, causal, numeric, temporal, entity_role
    claim_type: str = "proposition"
    numbers: list[NormalizedNumber] = Field(default_factory=list)
    dates: list[NormalizedDate] = Field(default_factory=list)
    units: list[NormalizedUnit] = Field(default_factory=list)
    confidence: float = 1.0

    model_config = ConfigDict(populate_by_name=True)


class ClaimAssessment(BaseModel):
    """Assessment of a single atomic claim against evidence."""

    claim: AtomicClaim
    verdict: ClaimVerdict
    confidence: float = 1.0
    supporting_span_ids: list[str] = Field(default_factory=list)
    supporting_quotes: list[str] = Field(default_factory=list)
    contradiction_quotes: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    verifier_name: str = "deterministic"
    verifier_version: str = "1"
    concise_rationale: str = ""


# ---------------------------------------------------------------------------
# Deterministic validators (WP A2)
# ---------------------------------------------------------------------------

# Unit normalization table
UNIT_MAP: dict[str, dict[str, str | float]] = {
    # Time
    "seconds": {"canonical": "seconds", "type": "time", "multiplier": 1.0},
    "second": {"canonical": "seconds", "type": "time", "multiplier": 1.0},
    "sec": {"canonical": "seconds", "type": "time", "multiplier": 1.0},
    "secs": {"canonical": "seconds", "type": "time", "multiplier": 1.0},
    "minutes": {"canonical": "minutes", "type": "time", "multiplier": 1.0},
    "minute": {"canonical": "minutes", "type": "time", "multiplier": 1.0},
    "min": {"canonical": "minutes", "type": "time", "multiplier": 1.0},
    "mins": {"canonical": "minutes", "type": "time", "multiplier": 1.0},
    "hours": {"canonical": "hours", "type": "time", "multiplier": 1.0},
    "hour": {"canonical": "hours", "type": "time", "multiplier": 1.0},
    "days": {"canonical": "days", "type": "time", "multiplier": 1.0},
    "day": {"canonical": "days", "type": "time", "multiplier": 1.0},
    "weeks": {"canonical": "weeks", "type": "time", "multiplier": 1.0},
    "week": {"canonical": "weeks", "type": "time", "multiplier": 1.0},
    "months": {"canonical": "months", "type": "time", "multiplier": 1.0},
    "month": {"canonical": "months", "type": "time", "multiplier": 1.0},
    "ms": {"canonical": "milliseconds", "type": "time", "multiplier": 1.0},
    "milliseconds": {"canonical": "milliseconds", "type": "time", "multiplier": 1.0},
    # Data / bytes
    "b": {"canonical": "bytes", "type": "data", "multiplier": 1.0},
    "bytes": {"canonical": "bytes", "type": "data", "multiplier": 1.0},
    "kb": {"canonical": "kilobytes", "type": "data", "multiplier": 1.0},
    "kilobytes": {"canonical": "kilobytes", "type": "data", "multiplier": 1.0},
    "mb": {"canonical": "megabytes", "type": "data", "multiplier": 1.0},
    "megabytes": {"canonical": "megabytes", "type": "data", "multiplier": 1.0},
    "gb": {"canonical": "gigabytes", "type": "data", "multiplier": 1.0},
    "gigabytes": {"canonical": "gigabytes", "type": "data", "multiplier": 1.0},
    # Distance
    "meters": {"canonical": "meters", "type": "distance", "multiplier": 1.0},
    "metres": {"canonical": "meters", "type": "distance", "multiplier": 1.0},
    "m": {"canonical": "meters", "type": "distance", "multiplier": 1.0},
    "kilometers": {"canonical": "kilometers", "type": "distance", "multiplier": 1000.0},
    "kilometres": {"canonical": "kilometers", "type": "distance", "multiplier": 1000.0},
    "km": {"canonical": "kilometers", "type": "distance", "multiplier": 1000.0},
    # Currency
    "usd": {"canonical": "usd", "type": "currency", "multiplier": 1.0},
    "$": {"canonical": "usd", "type": "currency", "multiplier": 1.0},
    "eur": {"canonical": "eur", "type": "currency", "multiplier": 1.0},
    "€": {"canonical": "eur", "type": "currency", "multiplier": 1.0},
    "gbp": {"canonical": "gbp", "type": "currency", "multiplier": 1.0},
    "£": {"canonical": "gbp", "type": "currency", "multiplier": 1.0},
}

# Negation markers
NEGATION_WORDS: set[str] = {
    "not",
    "no",
    "never",
    "neither",
    "nor",
    "none",
    "nobody",
    "nothing",
    "nowhere",
    "cannot",
    "can't",
    "don't",
    "doesn't",
    "didn't",
    "won't",
    "wouldn't",
    "couldn't",
    "shouldn't",
    "isn't",
    "aren't",
    "wasn't",
    "weren't",
    "hasn't",
    "haven't",
    "hadn't",
    "prohibited",
    "forbidden",
    "disallowed",
    "banned",
    "without",
    "unable",
    "except",
    "excluding",
    "absence",
}

# Causal relation markers (verb-based for simple sentences)
CAUSAL_RELATIONS: dict[str, str] = {
    "causes": "causes",
    "cause": "causes",
    "caused": "causes",
    "result in": "causes",
    "results in": "causes",
    "resulted in": "causes",
    "leads to": "causes",
    "lead to": "causes",
    "led to": "causes",
    "triggers": "causes",
    "triggered": "causes",
    "is caused by": "caused_by",
    "are caused by": "caused_by",
    "was caused by": "caused_by",
    "results from": "caused_by",
    "result from": "caused_by",
    "resulted from": "caused_by",
    "depends on": "caused_by",
    "depended on": "caused_by",
}

# Comparison direction markers
COMPARISON_DIRECTION: dict[str, str] = {
    "greater": "greater",
    "larger": "greater",
    "bigger": "greater",
    "higher": "greater",
    "more": "greater",
    "above": "greater",
    "exceeds": "greater",
    "exceed": "greater",
    "exceeded": "greater",
    "less": "less",
    "smaller": "less",
    "lower": "less",
    "fewer": "less",
    "below": "less",
    "under": "less",
    "before": "before",
    "after": "after",
    "increase": "increase",
    "decrease": "decrease",
    "enabled": "enabled",
    "disabled": "disabled",
}


def detect_polarity(text: str) -> Literal["affirmed", "negated", "unknown"]:
    """Detect whether a clause or sentence is negated.

    Handles simple negations and common double-negation patterns
    (e.g., "not uncommon", "not impossible").
    """
    if not text.strip():
        return "unknown"

    text_lower = text.lower().strip()

    # Detect common double-negation patterns BEFORE single negation detection
    double_negation_patterns = [
        "not uncommon",
        "not unknown",
        "not impossible",
        "not unlike",
        "not un",
        "not in",
        "not lacking",
        "not without",
    ]
    for pattern in double_negation_patterns:
        if pattern in text_lower:
            return "affirmed"

    # Check for sentence-start negation
    first_word = text_lower.split()[0].strip(".,!?;:") if text_lower else ""
    if first_word in {"not", "no", "never", "neither", "nor"}:
        return "negated"

    # Check for negation words in the first 15 tokens
    tokens = text_lower.split()
    main_content = tokens[: min(len(tokens), 15)]
    neg_words = [w.strip(".,!?;:") for w in main_content if w.strip(".,!?;:") in NEGATION_WORDS]

    if not neg_words:
        return "affirmed"

    return "negated" if len(neg_words) % 2 == 1 else "affirmed"


def detect_causal_direction(claim_text: str, evidence_text: str) -> tuple[str, str, str | None]:
    """Extract subject, object, causal direction from simple causal sentences.

    Returns (subject, object, relation_type) where relation_type is
    "causes" (A causes B) or "caused_by" (B is caused by A / A depends on B).
    """
    claim_lower = claim_text.lower().strip().rstrip(".")
    evidence_lower = evidence_text.lower().strip().rstrip(".")

    claim_causes = None
    evidence_causes = None

    for marker, rel in CAUSAL_RELATIONS.items():
        if marker in claim_lower:
            claim_causes = rel
        if marker in evidence_lower:
            evidence_causes = rel

    if claim_causes and evidence_causes:
        # Extract subjects and objects
        claim_subj = _extract_subject(claim_text)
        evidence_subj = _extract_subject(evidence_text)

        if claim_subj and evidence_subj:
            return (claim_subj, evidence_subj, f"claim_{claim_causes}_evidence_{evidence_causes}")

    return ("", "", None)


def _extract_subject(text: str) -> str | None:
    """Extract the grammatical subject from a simple sentence."""
    text = text.strip().rstrip(".!?")
    # Very simple heuristic: first noun-like word before a causal verb
    for marker in CAUSAL_RELATIONS:
        idx = text.lower().find(marker)
        if idx > 0:
            before = text[:idx].strip()
            words = before.split()
            if words:
                return words[-1].strip(".,;:")
    # Fallback: first noun-like content word
    for w in text.split():
        wc = w.strip(".,;:")
        if wc.lower() not in {"the", "a", "an", "this", "that", "these", "those"}:
            return wc
    return None


def check_entity_role_reversal(claim_text: str, evidence_text: str) -> bool:
    """Check if claim swaps subject and object roles compared to evidence.

    Looks for sentences where two entities appear in both claim and evidence
    but with swapped subject/object roles. Handles any transitive verb pattern
    like "X verbs Y" vs "Y verbs X".
    """
    # Find pairs of capitalized words (potential named entities) in both
    import re

    entities_claim = re.findall(r"\b[A-Z][a-z]*\b", claim_text)
    entities_ev = re.findall(r"\b[A-Z][a-z]*\b", evidence_text)

    # If both have the same two entities, check if they're swapped
    if len(entities_claim) >= 2 and len(entities_ev) >= 2:
        claim_set = set(entities_claim)
        ev_set = set(entities_ev)
        common = claim_set & ev_set
        if len(common) >= 2:
            # Both have the same two entities — check ordering
            claim_order = [e for e in entities_claim if e in common]
            ev_order = [e for e in entities_ev if e in common]
            if claim_order and ev_order:
                # Reversed if first entity in claim is second in evidence
                reversed_order = claim_order[0] == ev_order[-1] and claim_order[-1] == ev_order[0]
                return bool(reversed_order)

    return False


def _split_on_marker(text: str, marker: str) -> list[str]:
    """Split text on a marker (case-insensitive), returning up to 2 parts."""
    idx = text.lower().find(marker.lower())
    if idx < 0:
        return []
    before = text[:idx]
    after = text[idx + len(marker) :]
    return [before, after]


def check_negation_reversal(claim_text: str, evidence_text: str) -> bool:
    """Check if claim negates what evidence affirms (or vice versa)."""
    evidence_polarity = detect_polarity(evidence_text)
    claim_polarity = detect_polarity(claim_text)

    known = evidence_polarity != "unknown" and claim_polarity != "unknown"
    return evidence_polarity != claim_polarity and known


def normalize_number_text(text: str) -> list[NormalizedNumber]:
    """Extract and normalize numbers from text, handling commas, percentages, currencies."""
    results: list[NormalizedNumber] = []

    # Currency prefix
    currency_match = re.search(r"([\$€£¥])\s*([\d,]+(?:\.\d+)?)", text)
    if currency_match:
        raw = currency_match.group(0)
        prefix = currency_match.group(1)
        try:
            val = float(currency_match.group(2).replace(",", ""))
        except ValueError:
            val = 0.0
        results.append(NormalizedNumber(raw=raw, value=val, prefix=prefix, unit=prefix))

    # Percentages
    for m in re.finditer(r"([\d,]+(?:\.\d+)?)\s*%", text):
        raw = m.group(0)
        try:
            val = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        results.append(
            NormalizedNumber(raw=raw, value=val, is_percentage=True, percentage_value=val, unit="%")
        )

    # Ranges
    for m in re.finditer(r"([\d,]+(?:\.\d+)?)\s*(?:-|to|–)\s*([\d,]+(?:\.\d+)?)", text):
        try:
            start = float(m.group(1).replace(",", ""))
            end = float(m.group(2).replace(",", ""))
        except ValueError:
            continue
        results.append(
            NormalizedNumber(
                raw=m.group(0),
                value=(start + end) / 2,
                is_range=True,
                range_start=start,
                range_end=end,
            )
        )

    # Standalone numbers
    for m in re.finditer(r"(?<![\.\d])([\d,]+(?:\.\d+)?)(?![\.\d])(?!\s*%)(?!\s*[\$€£¥])", text):
        raw_num = m.group(0)
        if any(n.raw == raw_num or (n.is_range and raw_num in n.raw) for n in results):
            continue
        try:
            val = float(raw_num.replace(",", ""))
        except ValueError:
            continue
        results.append(NormalizedNumber(raw=raw_num, value=val))

    return results


def normalize_unit(text: str) -> list[NormalizedUnit]:
    """Extract and normalize units from text."""
    results: list[NormalizedUnit] = []
    # Match word tokens that might be units
    tokens = re.findall(r"\b[a-zA-Z]+\b", text)
    for token in tokens:
        lower = token.lower()
        if lower in UNIT_MAP:
            info = UNIT_MAP[lower]
            results.append(
                NormalizedUnit(
                    raw=token,
                    canonical=str(info["canonical"]),
                    unit_type=str(info["type"]),
                    multiplier_to_base=float(info["multiplier"]),
                )
            )
    # Also check for unit abbreviations attached to numbers
    for match in re.finditer(r"(\d[\d,]*\.?\d*)\s*([a-zA-Z]{1,5})\b", text):
        unit_str = match.group(2).lower()
        if unit_str in UNIT_MAP:
            info = UNIT_MAP[unit_str]
            results.append(
                NormalizedUnit(
                    raw=match.group(2),
                    canonical=str(info["canonical"]),
                    unit_type=str(info["type"]),
                    multiplier_to_base=float(info["multiplier"]),
                )
            )
    return results


def normalize_date(text: str, anchor: datetime | None = None) -> list[NormalizedDate]:
    """Extract and normalize dates from text."""
    results: list[NormalizedDate] = []
    # ISO dates
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        results.append(
            NormalizedDate(raw=m.group(0), iso_date=m.group(0), year=year, month=month, day=day)
        )
    # Named months
    for m in re.finditer(
        r"\b((?:January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{1,2},?\s*\d{4})\b",
        text,
        re.IGNORECASE,
    ):
        raw = m.group(0)
        try:
            dt = datetime.strptime(raw.replace(",", ""), "%B %d %Y")
            results.append(
                NormalizedDate(
                    raw=raw,
                    iso_date=dt.strftime("%Y-%m-%d"),
                    year=dt.year,
                    month=dt.month,
                    day=dt.day,
                )
            )
        except ValueError:
            pass
    return results


def check_number_mismatch(claim_text: str, evidence_text: str) -> list[str]:
    """Check for numerical mismatches between claim and evidence.

    Returns list of reason codes for each mismatch found.
    """
    reasons: list[str] = []
    evidence_numbers = normalize_number_text(evidence_text)
    claim_numbers = normalize_number_text(claim_text)

    if not evidence_numbers or not claim_numbers:
        return reasons

    # Extract key context words from both sentences for cross-referencing
    def _context_words(text: str) -> set[str]:
        words = set(re.findall(r"\b[a-zA-Z]{4,}\b", text.lower()))
        stopwords = {
            "with",
            "from",
            "that",
            "this",
            "these",
            "those",
            "what",
            "which",
            "there",
            "their",
            "than",
            "they",
            "have",
            "been",
            "were",
            "into",
            "over",
            "such",
            "each",
            "also",
        }
        return words - stopwords

    ctx_ev = _context_words(evidence_text)
    ctx_claim = _context_words(claim_text)
    common_context = ctx_ev & ctx_claim  # words appearing in both sentences

    for cn in claim_numbers:
        for en in evidence_numbers:
            # Compare numbers with matching units (including empty)
            if cn.unit == en.unit and cn.is_percentage == en.is_percentage:
                # Skip empty-unit comparison if there's no shared context
                if not cn.unit and not en.unit and not common_context:
                    continue
                if abs(cn.value - en.value) > 0.001:
                    reasons.append(f"number_mismatch:{cn.raw}:{cn.value}:{cn.unit}:{en.value}")
                    break
    return reasons


def check_unit_mismatch(claim_text: str, evidence_text: str) -> list[str]:
    """Check for unit mismatches between claim and evidence.

    Returns list of reason codes.
    """
    reasons: list[str] = []
    evidence_units = normalize_unit(evidence_text)
    claim_units = normalize_unit(claim_text)

    # Group units by type for evidence
    ev_by_type: dict[str, list[NormalizedUnit]] = {}
    for u in evidence_units:
        if u.unit_type:
            ev_by_type.setdefault(u.unit_type, []).append(u)

    for cu in claim_units:
        if cu.unit_type and cu.unit_type in ev_by_type:
            # Same type, check if canonical is different
            ev_canonicals = {e.canonical for e in ev_by_type[cu.unit_type]}
            if cu.canonical not in ev_canonicals:
                reasons.append(f"unit_mismatch:{cu.raw}:{cu.canonical}:{list(ev_canonicals)}")
    return reasons


def check_unsupported_entities(claim_text: str, evidence_text: str) -> list[str]:
    """Check for named entities in claim that don't appear in evidence.

    Returns list of unsupported entity names.
    """
    unsupported: list[str] = []
    evidence_lower = evidence_text.lower()

    # Extract capitalized words (potential proper nouns) — words containing
    # uppercase letters (camelCase, PascalCase, ALLCAPS, or Title Case)
    for match in re.finditer(r"\b[A-Z][A-Za-z0-9]*\b", claim_text):
        entity = match.group(0)
        if entity.lower() not in evidence_lower:
            unsupported.append(entity)

    return unsupported
