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
    # Time (base: seconds) — real multipliers so conversion-aware checks see
    # "30 minutes" ≠ "30 seconds" at base value while "0.5 hours" == "30 min".
    "seconds": {"canonical": "seconds", "type": "time", "multiplier": 1.0},
    "second": {"canonical": "seconds", "type": "time", "multiplier": 1.0},
    "sec": {"canonical": "seconds", "type": "time", "multiplier": 1.0},
    "secs": {"canonical": "seconds", "type": "time", "multiplier": 1.0},
    "minutes": {"canonical": "minutes", "type": "time", "multiplier": 60.0},
    "minute": {"canonical": "minutes", "type": "time", "multiplier": 60.0},
    "min": {"canonical": "minutes", "type": "time", "multiplier": 60.0},
    "mins": {"canonical": "minutes", "type": "time", "multiplier": 60.0},
    "hours": {"canonical": "hours", "type": "time", "multiplier": 3600.0},
    "hour": {"canonical": "hours", "type": "time", "multiplier": 3600.0},
    "hr": {"canonical": "hours", "type": "time", "multiplier": 3600.0},
    "hrs": {"canonical": "hours", "type": "time", "multiplier": 3600.0},
    "days": {"canonical": "days", "type": "time", "multiplier": 86400.0},
    "day": {"canonical": "days", "type": "time", "multiplier": 86400.0},
    "weeks": {"canonical": "weeks", "type": "time", "multiplier": 604800.0},
    "week": {"canonical": "weeks", "type": "time", "multiplier": 604800.0},
    "months": {"canonical": "months", "type": "time", "multiplier": 2592000.0},  # 30 days
    "month": {"canonical": "months", "type": "time", "multiplier": 2592000.0},  # 30 days
    "ms": {"canonical": "milliseconds", "type": "time", "multiplier": 0.001},
    "milliseconds": {"canonical": "milliseconds", "type": "time", "multiplier": 0.001},
    "millisecond": {"canonical": "milliseconds", "type": "time", "multiplier": 0.001},
    # Data / bytes (base: bytes, decimal prefixes)
    "b": {"canonical": "bytes", "type": "data", "multiplier": 1.0},
    "bytes": {"canonical": "bytes", "type": "data", "multiplier": 1.0},
    "byte": {"canonical": "bytes", "type": "data", "multiplier": 1.0},
    "kb": {"canonical": "kilobytes", "type": "data", "multiplier": 1000.0},
    "kilobytes": {"canonical": "kilobytes", "type": "data", "multiplier": 1000.0},
    "kilobyte": {"canonical": "kilobytes", "type": "data", "multiplier": 1000.0},
    "mb": {"canonical": "megabytes", "type": "data", "multiplier": 1e6},
    "megabytes": {"canonical": "megabytes", "type": "data", "multiplier": 1e6},
    "megabyte": {"canonical": "megabytes", "type": "data", "multiplier": 1e6},
    "gb": {"canonical": "gigabytes", "type": "data", "multiplier": 1e9},
    "gigabytes": {"canonical": "gigabytes", "type": "data", "multiplier": 1e9},
    "gigabyte": {"canonical": "gigabytes", "type": "data", "multiplier": 1e9},
    # Distance
    "meters": {"canonical": "meters", "type": "distance", "multiplier": 1.0},
    "metres": {"canonical": "meters", "type": "distance", "multiplier": 1.0},
    "m": {"canonical": "meters", "type": "distance", "multiplier": 1.0},
    "kilometers": {"canonical": "kilometers", "type": "distance", "multiplier": 1000.0},
    "kilometres": {"canonical": "kilometers", "type": "distance", "multiplier": 1000.0},
    "km": {"canonical": "kilometers", "type": "distance", "multiplier": 1000.0},
    "centimeters": {"canonical": "centimeters", "type": "distance", "multiplier": 0.01},
    "centimeter": {"canonical": "centimeters", "type": "distance", "multiplier": 0.01},
    "centimetres": {"canonical": "centimeters", "type": "distance", "multiplier": 0.01},
    "centimetre": {"canonical": "centimeters", "type": "distance", "multiplier": 0.01},
    "cm": {"canonical": "centimeters", "type": "distance", "multiplier": 0.01},
    "millimeters": {"canonical": "millimeters", "type": "distance", "multiplier": 0.001},
    "millimeter": {"canonical": "millimeters", "type": "distance", "multiplier": 0.001},
    "millimetres": {"canonical": "millimeters", "type": "distance", "multiplier": 0.001},
    "millimetre": {"canonical": "millimeters", "type": "distance", "multiplier": 0.001},
    "mm": {"canonical": "millimeters", "type": "distance", "multiplier": 0.001},
    # Volume (base: liters) — the liter/milliliter family is what unit-error
    # defects look like in practice ("50 milliliters" for "50 liters").
    "liters": {"canonical": "liters", "type": "volume", "multiplier": 1.0},
    "liter": {"canonical": "liters", "type": "volume", "multiplier": 1.0},
    "litres": {"canonical": "liters", "type": "volume", "multiplier": 1.0},
    "litre": {"canonical": "liters", "type": "volume", "multiplier": 1.0},
    "milliliters": {"canonical": "milliliters", "type": "volume", "multiplier": 0.001},
    "milliliter": {"canonical": "milliliters", "type": "volume", "multiplier": 0.001},
    "millilitres": {"canonical": "milliliters", "type": "volume", "multiplier": 0.001},
    "millilitre": {"canonical": "milliliters", "type": "volume", "multiplier": 0.001},
    "ml": {"canonical": "milliliters", "type": "volume", "multiplier": 0.001},
    # Mass (base: kilograms)
    "kilograms": {"canonical": "kilograms", "type": "mass", "multiplier": 1.0},
    "kilogram": {"canonical": "kilograms", "type": "mass", "multiplier": 1.0},
    "kg": {"canonical": "kilograms", "type": "mass", "multiplier": 1.0},
    "grams": {"canonical": "grams", "type": "mass", "multiplier": 0.001},
    "gram": {"canonical": "grams", "type": "mass", "multiplier": 0.001},
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


_ROLE_TRIPLE = re.compile(
    r"\b([A-Z][A-Za-z0-9]*)"  # first entity
    r"((?:\s+[a-z][a-zA-Z-]*){1,4})"  # short lowercase predicate
    r"\s+([A-Z][A-Za-z0-9]*)\b"  # second entity
)


def check_entity_role_reversal(claim_text: str, evidence_text: str) -> bool:
    """Check if claim swaps subject and object roles compared to evidence.

    A role reversal is a VERB-ANCHORED pattern: the same two entities around
    the same transitive verb, in opposite order ("Bob approved Alice" vs
    "Alice approved Bob"). Merely sharing two capitalized tokens whose textual
    orders differ is NOT a reversal — unrelated nouns ("Devices ... March")
    legitimately appear in any order and flagging them false-rejected
    entailed answers.

    Two shapes are detected:

    * capitalized triples via :data:`_ROLE_TRIPLE` (proper-noun subjects);
    * an exact token exchange for common-noun subjects — claim
      ``X ships Y`` vs evidence ``Y ships X``, i.e. evidence equals the
      claim with its leading noun phrase and trailing noun phrase swapped
      around an identical middle that carries a verb.
    """

    def triples(text: str) -> list[tuple[str, str, str]]:
        found: list[tuple[str, str, str]] = []
        for m in _ROLE_TRIPLE.finditer(text):
            predicate_words = m.group(2).split()
            if not predicate_words:
                continue
            verb = predicate_words[-1].lower().rstrip(".,;:!?'\"")
            if len(verb) < 3 or verb in _DISCOURSE_WORDS:
                continue
            found.append((m.group(1), verb, m.group(3)))
        return found

    for c_first, c_verb, c_second in triples(claim_text):
        for e_first, e_verb, e_second in triples(evidence_text):
            if c_verb == e_verb and c_first == e_second and c_second == e_first:
                return True
    return _exchange_reversal(claim_text, evidence_text)


# Words that may appear inside the exchanged middle but cannot anchor it —
# determiners, prepositions, auxiliaries. The anchor must be a content word,
# which in this shape is the transitive verb (or verb + object).
_EXCHANGE_NON_ANCHORS = frozenset(
    {
        "the",
        "a",
        "an",
        "to",
        "by",
        "with",
        "from",
        "for",
        "into",
        "onto",
        "over",
        "under",
        "after",
        "before",
        "during",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "its",
        "their",
        "his",
        "her",
        "each",
        "every",
        "and",
        "or",
    }
)


def _exchange_reversal(claim_text: str, evidence_text: str) -> bool:
    """Common-noun role swap: claim = PRE + MID + SUF with evidence =
    SUF + MID + PRE (token-exact), where MID anchors on a content word.

    "the warehouse ships sensors to the assembly plant" ↔
    "the assembly plant ships sensors to the warehouse": X/M/Y → Y/M/X.
    Exact token equality keeps the false-positive rate at zero on
    paraphrased entailment (different wording can never match).
    """

    def tokenize(text: str) -> list[str]:
        return [w.strip(".,;:!?'\"()").lower() for w in text.split() if w.strip(".,;:!?'\"()")]

    ct = tokenize(claim_text)
    n = len(ct)
    if n < 4:
        return False

    def matches(et: list[str]) -> bool:
        # claim = pre + mid + suf ; evidence == suf + mid + pre
        for i in range(1, min(5, n - 1)):  # leading noun phrase
            for m in range(1, min(7, n - i)):  # middle (verb phrase)
                pre, mid, suf = ct[:i], ct[i : i + m], ct[i + m :]
                if not suf or pre == suf:
                    continue
                if et != suf + mid + pre:
                    continue
                if any(w not in _EXCHANGE_NON_ANCHORS and len(w) >= 3 for w in mid):
                    return True
        return False

    for sentence in re.split(r"(?<=[.!?])\s+", evidence_text):
        et = tokenize(sentence)
        if len(et) == n and matches(et):
            return True
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


def _quantities_with_base(text: str) -> list[tuple[float, float, str]]:
    """(raw value, value × unit multiplier, unit type) per unit-attached number.

    Powers the conversion-aware rescue in ``check_number_mismatch``: "2 meters"
    and "200 centimeters" are the SAME quantity and must never be reported as
    a numerical contradiction.
    """
    out: list[tuple[float, float, str]] = []
    for m in re.finditer(r"(\d[\d,]*\.?\d*)\s*([a-zA-Z]{1,12})\b", text):
        info = UNIT_MAP.get(m.group(2).lower())
        if not info:
            continue
        try:
            raw = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        out.append((raw, raw * float(info["multiplier"]), str(info["type"])))
    return out


def _conversion_equivalent(
    claim_q: list[tuple[float, float, str]],
    evidence_q: list[tuple[float, float, str]],
    claim_value: float,
    evidence_value: float,
) -> bool:
    """True when this exact number pair is a same-quantity unit conversion."""
    return any(
        c_raw == claim_value
        and e_raw == evidence_value
        and c_type == e_type
        and abs(c_base - e_base) <= 0.001
        for c_raw, c_base, c_type in claim_q
        for e_raw, e_base, e_type in evidence_q
    )


def check_number_mismatch(claim_text: str, evidence_text: str) -> list[str]:
    """Check for numerical mismatches between claim and evidence.

    Returns list of reason codes for each mismatch found.
    """
    reasons: list[str] = []
    evidence_numbers = normalize_number_text(evidence_text)
    claim_numbers = normalize_number_text(claim_text)

    if not evidence_numbers or not claim_numbers:
        return reasons

    claim_q = _quantities_with_base(claim_text)
    evidence_q = _quantities_with_base(evidence_text)

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
                if abs(cn.value - en.value) > 0.001 and not _conversion_equivalent(
                    claim_q, evidence_q, cn.value, en.value
                ):
                    reasons.append(f"number_mismatch:{cn.raw}:{cn.value}:{cn.unit}:{en.value}")
                    break
    return reasons


def _base_equivalent(claim_text: str, evidence_text: str, unit_type: str) -> bool:
    """True when both texts carry quantities of ``unit_type`` whose base-unit
    values agree — i.e. the same measurement expressed in convertible units
    ("2 meters" vs "200 centimeters"), which is not a mismatch."""

    def bases(text: str) -> list[float]:
        return [base for _, base, t in _quantities_with_base(text) if t == unit_type]

    return any(abs(cb - eb) <= 0.001 for cb in bases(claim_text) for eb in bases(evidence_text))


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
                # A differing canonical whose measured quantity is
                # base-equivalent is a unit CONVERSION, not a contradiction
                # ("the cable is 2 meters long" vs "200 centimeters long").
                if _base_equivalent(claim_text, evidence_text, cu.unit_type):
                    continue
                reasons.append(f"unit_mismatch:{cu.raw}:{cu.canonical}:{list(ev_canonicals)}")
    return reasons


#: Words capitalized by grammar or position, never proper nouns. Without this
#: stoplist the entity check flagged sentence openers ("According to the
#: material: ...") as fabricated entities and contradicted faithful answers —
#: caught the moment the check was wired into the acceptance path and run
#: against the offline provider corpus.
_DISCOURSE_WORDS: frozenset[str] = frozenset(
    [
        "a",
        "according",
        "additionally",
        "all",
        "also",
        "an",
        "any",
        "as",
        "at",
        "above",
        "after",
        "before",
        "because",
        "below",
        "both",
        "but",
        "by",
        "during",
        "each",
        "every",
        "finally",
        "first",
        "following",
        "for",
        "from",
        "further",
        "furthermore",
        "given",
        "hence",
        "here",
        "he",
        "her",
        "hers",
        "him",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "it",
        "its",
        "let",
        "lets",
        "may",
        "might",
        "moreover",
        "next",
        "no",
        "not",
        "note",
        "of",
        "on",
        "once",
        "one",
        "only",
        "or",
        "other",
        "our",
        "out",
        "over",
        "per",
        "second",
        "she",
        "should",
        "since",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "third",
        "this",
        "those",
        "thus",
        "to",
        "therefore",
        "under",
        "until",
        "up",
        "upon",
        "us",
        "using",
        "we",
        "were",
        "what",
        "when",
        "where",
        "whether",
        "which",
        "while",
        "who",
        "whom",
        "whose",
        "why",
        "will",
        "with",
        "within",
        "without",
        "you",
        "your",
    ]
)


def _entity_in_evidence(entity_lower: str, evidence_lower: str) -> bool:
    """Substring membership with singular/plural tolerance.

    A faithful paraphrase may restate "each unit" as "Units" — flagging the
    plural as a fabricated entity false-rejects entailed answers. Only the
    morphology changes; the referent is still supported.
    """
    if entity_lower in evidence_lower:
        return True
    candidates = (
        entity_lower[:-1],  # units -> unit
        entity_lower[:-2],  # boxes -> box
        entity_lower[:-3] + "y",  # companies -> company
    )
    return any(len(c) >= 3 and c in evidence_lower for c in candidates)


def check_unsupported_entities(claim_text: str, evidence_text: str) -> list[str]:
    """Check for named entities in claim that don't appear in evidence.

    Candidate entities are capitalized tokens (Title Case, ALLCAPS, or
    PascalCase) whose lowercase form is not a discourse word — sentence
    position alone does not exempt a token, so a fabricated sentence-initial
    name ("Bob approved Carol") is still caught, while grammatical capitals
    ("According", "The") never are. Plural forms of an attested singular are
    supported (see ``_entity_in_evidence``).

    Returns list of unsupported entity names.
    """
    unsupported: list[str] = []
    evidence_lower = evidence_text.lower()

    for match in re.finditer(r"\b[A-Z][A-Za-z0-9]*\b", claim_text):
        entity = match.group(0)
        if entity.lower() in _DISCOURSE_WORDS:
            continue
        if not _entity_in_evidence(entity.lower(), evidence_lower):
            unsupported.append(entity)

    return unsupported
