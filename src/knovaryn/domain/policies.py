"""Domain policies (spec §6.4, §12.7, §14.3, §15).

Pure-python policy logic: evidence/provenance minimums (6.4), preference-pair
policy (12.7: length-ratio band, artifact separability), default acceptance
thresholds (14.3), and license defaults (15). No framework imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .schemas import LicenseStatus, QualityStatus, TrainingExample


# ---------------------------------------------------------------------------
# Section 6.4 — provenance minimum for an exportable example
# ---------------------------------------------------------------------------


@dataclass
class ProvenanceCheck:
    ok: bool
    missing: list[str] = field(default_factory=list)


def check_provenance_minimum(ex: TrainingExample, *, require_evidence: bool = True) -> ProvenanceCheck:
    missing: list[str] = []
    if not ex.source_document_ids:
        missing.append("source_document_ids")
    if require_evidence and not ex.source_span_ids:
        missing.append("source_span_ids")
    if not ex.content_hash:
        missing.append("content_hash")
    if not ex.generation_candidate_ids:
        missing.append("generation_candidate_ids")
    if ex.quality_status not in (QualityStatus.accepted, QualityStatus.review):
        missing.append("quality_status_not_reviewable")
    return ProvenanceCheck(ok=not missing, missing=missing)


# ---------------------------------------------------------------------------
# Section 14.3 — default acceptance policy
# ---------------------------------------------------------------------------


@dataclass
class AcceptancePolicy:
    minimum_overall: float = 0.82
    minimum_grounding: float = 0.90
    minimum_instruction_fulfillment: float = 0.80
    minimum_preference_signal: float = 0.70
    minimum_artifact_resistance: float = 0.75
    reject_on_high_confidence_pii: bool = True
    reject_on_blocked_license: bool = True
    require_evidence: bool = True
    judge_disagreement: str = "review"

    def assess(self, dims: dict[str, float], *, is_preference: bool) -> tuple[bool, list[str], QualityStatus]:
        reasons: list[str] = []
        overall = dims.get("overall", sum(dims.values()) / max(len(dims), 1))
        if dims.get("grounding", 1.0) < self.minimum_grounding:
            reasons.append(f"grounding<{self.minimum_grounding}")
        if dims.get("instruction_fulfillment", 1.0) < self.minimum_instruction_fulfillment:
            reasons.append(f"instruction_fulfillment<{self.minimum_instruction_fulfillment}")
        if overall < self.minimum_overall:
            reasons.append(f"overall<{self.minimum_overall}")
        if is_preference and dims.get("preference_signal", 0.0) < self.minimum_preference_signal:
            reasons.append(f"preference_signal<{self.minimum_preference_signal}")
        if dims.get("artifact_resistance", 1.0) < self.minimum_artifact_resistance:
            reasons.append(f"artifact_resistance<{self.minimum_artifact_resistance}")
        if reasons:
            return False, reasons, QualityStatus.rejected
        return True, reasons, QualityStatus.accepted


# ---------------------------------------------------------------------------
# Section 12.7 — preference-pair policy
# ---------------------------------------------------------------------------

_LENGTH_RE = re.compile(r"(\d+)")


def approximate_tokens(text: str) -> int:
    """Cheap deterministic token estimate (words + punctuation)."""
    if not text:
        return 0
    return max(1, len(text.split()))


def length_ratio(chosen_text: str, rejected_text: str) -> float:
    c = approximate_tokens(chosen_text)
    r = approximate_tokens(rejected_text)
    if r == 0:
        return 0.0
    return c / r


def check_length_band(chosen_text: str, rejected_text: str, *, lo: float = 0.80, hi: float = 1.25) -> tuple[bool, float]:
    ratio = length_ratio(chosen_text, rejected_text)
    return (lo <= ratio <= hi), ratio


# --- Superficial artifact detection (§12.7, §14.7) ---
_REFUSAL_PHRASES = re.compile(
    r"(i can'?t|i cannot|cannot help|i'?m (sorry )?not able|i don'?t (have|know)|cannot provide)",
    re.IGNORECASE,
)
_FORMAT_MARKERS = re.compile(r"(^\s*(#|\*|-|\d\.)\s)", re.MULTILINE)


@dataclass
class ArtifactFeatures:
    token_count: int
    bullet_count: int
    heading_count: int
    refusal_count: int
    citation_count: int
    punct_count: int
    has_format: bool

    @classmethod
    def from_text(cls, text: str) -> "ArtifactFeatures":
        return cls(
            token_count=len(text.split()),
            bullet_count=len(_FORMAT_MARKERS.findall(text)),
            heading_count=text.count("## "),
            refusal_count=len(_REFUSAL_PHRASES.findall(text)),
            citation_count=text.count("[") + text.count("]"),
            punct_count=sum(c in "!?;:" for c in text),
            has_format=bool(_FORMAT_MARKERS.search(text)),
        )


def preference_is_trivially_separable(chosen: str, rejected: str, *, threshold: float = 0.2) -> tuple[bool, dict[str, float]]:
    """Estimate whether chosen/negative labels are trivially separable by
    superficial features (§14.7). Return (separable?, feature deltas 0..1).
    """
    lift: dict[str, float] = {}
    for name in ("token_count", "bullet_count", "heading_count", "refusal_count", "citation_count", "punct_count"):
        c = getattr(ArtifactFeatures.from_text(chosen), name)
        r = getattr(ArtifactFeatures.from_text(rejected), name)
        denom = max(c, r, 1)
        lift[name] = abs(c - r) / denom
    has_fmt_c = ArtifactFeatures.from_text(chosen).has_format
    has_fmt_r = ArtifactFeatures.from_text(rejected).has_format
    lift["format_diff"] = 1.0 if has_fmt_c != has_fmt_r else 0.0
    worst = max(lift.values()) if lift else 0.0
    return worst > threshold, lift


# ---------------------------------------------------------------------------
# Section 15 — license defaults
# ---------------------------------------------------------------------------


def default_license_status(declared: str | None) -> LicenseStatus:
    """Unknown license defaults to review (spec §15.2), never public-allowed."""
    if not declared:
        return LicenseStatus.unknown
    d = declared.strip().lower()
    if d in {"unknown", "", "unlicensed", "proprietary-not-declared"}:
        return LicenseStatus.unknown
    if d.startswith("public domain") or "cc0" in d or d in {"mit", "apache-2.0", "apache 2.0", "bsd", "bsd-3-clause", "unlicense"}:
        return LicenseStatus.allowed
    if d in {"proprietary", "closed", "all rights reserved", "confidential"}:
        return LicenseStatus.blocked
    return LicenseStatus.review


# ---------------------------------------------------------------------------
# Section 8.6 — prompt-injection markers in source text
# ---------------------------------------------------------------------------

INJECTION_PATTERNS = [
    re.compile(r"ignore (all )?(prior|previous|above) (instructions?|rules)", re.IGNORECASE),
    re.compile(r"disregard (all )?(prior|previous) instructions", re.IGNORECASE),
    re.compile(r"you are now", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"<\|im_start\|>", re.IGNORECASE),
]


def detect_injection_patterns(text: str) -> list[str]:
    """Return matched injection-pattern labels found in untrusted source text."""
    hits: list[str] = []
    for pat in INJECTION_PATTERNS:
        if pat.search(text):
            hits.append(pat.pattern)
    return hits
