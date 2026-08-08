"""PII detection (spec §14.5) and license policy (spec §14.6).

Deterministic heuristic scanners (no network, no ML model): regex + context
patterns for emails, phones, SSN, credit cards, IP addresses. License policy
maps declared license identifiers to allowed / review / blocked. These feed
the quarantine gate and per-example artifact-resistance validators.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ...domain.schemas import LicenseStatus


# ---------------------------------------------------------------------------
# PII
# ---------------------------------------------------------------------------

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CC = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_PHONE = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email", _EMAIL),
    ("ssn", _SSN),
    ("credit_card", _CC),
    ("phone", _PHONE),
    ("ipv4", _IPV4),
]

# high-confidence personal identifiers that should trigger quarantine / rejection
_HIGH_CONFIDENCE = {"email", "ssn", "credit_card"}

# context words that make a token-lookalike more likely to be genuine PII
_CONTEXT = re.compile(
    r"\b(email|phone|ssn|social security|credit card|card number|address|telephone|contact)\b",
    re.IGNORECASE,
)


@dataclass
class PIIFinding:
    kind: str
    snippet: str
    confidence: str  # high | medium | low
    position: int = 0


@dataclass
class PIIScanResult:
    findings: list[PIIFinding] = field(default_factory=list)

    @property
    def has_high_confidence(self) -> bool:
        return any(f.confidence == "high" for f in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_count": len(self.findings),
            "high_confidence": self.has_high_confidence,
            "findings": [vars(f) for f in self.findings],
        }


def scan_pii(text: str) -> PIIScanResult:
    """Scan free text for likely PII. Conservative: flags lookalikes with
    context words as high confidence, bare lookalikes as medium."""
    result = PIIScanResult()
    if not text:
        return result
    for kind, pat in _PATTERNS:
        for match in pat.finditer(text):
            snippet = match.group(0).strip()
            if kind == "ipv4" and not _looks_real_ip(snippet):
                continue
            if kind == "credit_card" and not _passes_luhn_digits(snippet):
                continue
            low = len(snippet) <= 6
            confidence = "high"
            if low:
                confidence = "medium"
            elif kind not in _HIGH_CONFIDENCE and not _CONTEXT.search(text[max(0, match.start() - 40): match.end() + 40]):
                confidence = "medium"
            result.findings.append(PIIFinding(kind=kind, snippet=snippet, confidence=confidence, position=match.start()))
    return result


def _looks_real_ip(snippet: str) -> bool:
    parts = snippet.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(p) <= 255 for p in parts)
    except ValueError:
        return False


def _passes_luhn_digits(snippet: str) -> bool:
    digits = [int(c) for c in snippet if c.isdigit()]
    if len(digits) not in (13, 15, 16, 19):
        return True  # ambiguous; report as medium not excluded
    total = 0
    double = False
    for d in reversed(digits):
        if double:
            d2 = d * 2
            total += d2 - 9 if d2 > 9 else d2
        else:
            total += d
        double = not double
    return total % 10 == 0


# ---------------------------------------------------------------------------
# License policy
# ---------------------------------------------------------------------------

_ALLOWED = {
    "cc0", "cc-by", "cc-by-sa", "cc-by-4.0", "cc-by-sa-4.0", "cc0-1.0", "cc-by-4.0",
    "mit", "apache-2.0", "bsd-3-clause", "bsd-2-clause", "unlicense", "public domain",
    "open government", "odc-by", "odc-odbl",
}
_REVIEW = {
    "cc-by-nc", "cc-by-nc-sa", "cc-by-nc-nd", "gfdl", "lgpl", "gpl-3.0", "gpl-2.0",
    "ms-pl", "proprietary", "custom", "unknown",
}
_BLOCKED = {"cc-by-nd", "cc-by-nc-nd", "all rights reserved", "copyright"}


class LicensePolicy:
    def __init__(self, *, default_status: LicenseStatus = LicenseStatus.review) -> None:
        self.default_status = default_status

    def classify(self, declared: str | None) -> LicenseStatus:
        if not declared:
            return self.default_status
        key = declared.strip().lower()
        if key in _BLOCKED:
            return LicenseStatus.blocked
        if key in _ALLOWED:
            return LicenseStatus.allowed
        for token in _ALLOWED:
            if key.endswith(token) or token in key:
                return LicenseStatus.allowed
        if key in _REVIEW:
            return LicenseStatus.review
        return self.default_status


def license_status(declared: str | None) -> LicenseStatus:
    return LicensePolicy().classify(declared)
