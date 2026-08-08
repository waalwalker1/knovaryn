"""Privacy policy (spec §15).

Classifies documents/examples by PII exposure and drives the privacy report
included in release bundles. High-confidence PII triggers review/block; the
privacy report summarizes findings without leaking the PII values themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..validation.scanners import PIIFinding, scan_pii


@dataclass
class PrivacyClassification:
    classification: str = "clean"  # clean | low | moderate | high
    high_confidence_count: int = 0
    findings: list[PIIFinding] = field(default_factory=list)
    sample_kinds: list[str] = field(default_factory=list)


def classify_text(text: str) -> PrivacyClassification:
    result = scan_pii(text)
    kinds = sorted({f.kind for f in result.findings})
    high_count = sum(1 for f in result.findings if f.confidence == "high")
    if high_count >= 2 or "ssn" in kinds or "credit_card" in kinds:
        classification = "high"
    elif high_count == 1:
        classification = "moderate"
    elif result.findings:
        classification = "low"
    else:
        classification = "clean"
    return PrivacyClassification(
        classification=classification,
        high_confidence_count=high_count,
        findings=result.findings,
        sample_kinds=kinds,
    )


@dataclass
class PrivacyReport:
    classified_documents: int = 0
    high_confidence_total: int = 0
    sample_kinds_seen: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)  # doc identifiers blocked

    def to_dict(self) -> dict[str, Any]:
        return {
            "classified_documents": self.classified_documents,
            "high_confidence_total": self.high_confidence_total,
            "sample_kinds_seen": sorted(self.sample_kinds_seen),
            "blocked_count": len(self.blocked),
            "blocked": list(self.blocked),
        }

    @classmethod
    def from_classifications(cls, classifications: list[tuple[str, PrivacyClassification]]) -> "PrivacyReport":
        report = cls()
        for doc_id, c in classifications:
            report.classified_documents += 1
            report.high_confidence_total += c.high_confidence_count
            report.sample_kinds_seen.extend(k for k in c.sample_kinds if k not in report.sample_kinds_seen)
            if c.classification == "high":
                report.blocked.append(doc_id)
        return report
