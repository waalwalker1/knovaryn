"""Source license registry and publication gate (spec §15.1–15.6).

Implements the *policy* half of the license/privacy controls that the pipeline
and publication path rely on:

* :func:`SourceLicenseRecord.inspect` — per-source license/provenance decision
  (declared license → ``allowed | review | blocked``, plus PII findings).
* :class:`LicenseAndPrivacyReport` — aggregates per-source records into the
  license + privacy summaries that appear in release bundles.
* :func:`publication_gate` — the §15.6 rule: publication is blocked unless every
  included source has an approved redistribution decision and there is no
  unresolved blocked source or high-confidence PII.

This is policy code only; it confers no rights. Final legal decisions remain
with the operator. Unknown license defaults to ``review`` (never auto-allowed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.schemas import LicenseStatus
from ..infrastructure.privacy.report import PrivacyClassification, PrivacyReport, classify_text
from ..infrastructure.validation.scanners import PIIScanResult, license_status, scan_pii

PUBLIC_REDISTRIBUTABLE = (LicenseStatus.allowed,)


@dataclass
class SourceLicenseRecord:
    """One source's license/provenance + privacy decision (spec §15.2 registry)."""

    source_id: str
    original_name: str
    declared_license: str | None = None
    license_status: LicenseStatus = LicenseStatus.review
    license_confidence: str = "policy"
    access_restriction: str = "none"
    redistribution: str = "undecided"
    required_attribution: str = ""
    share_alike_or_output_conditions: str = ""
    reviewer: str = "automatic-policy"
    pii: PIIScanResult = field(default_factory=PIIScanResult)
    privacy: PrivacyClassification = field(default_factory=PrivacyClassification)

    @classmethod
    def inspect(
        cls,
        *,
        source_id: str,
        original_name: str,
        text: str,
        declared_license: str | None,
        reviewer: str = "automatic-policy",
    ) -> SourceLicenseRecord:
        """Build a registry record from a declared license and source text."""
        status = license_status(declared_license)
        return cls(
            source_id=source_id,
            original_name=original_name,
            declared_license=declared_license,
            license_status=status,
            redistribution="approved-for-redistribution"
            if status in PUBLIC_REDISTRIBUTABLE
            else "undecided",
            reviewer=reviewer,
            pii=scan_pii(text),
            privacy=classify_text(text),
        )

    def is_approved_for_public_release(self) -> bool:
        return (
            self.license_status in PUBLIC_REDISTRIBUTABLE and self.privacy.classification != "high"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "original_name": self.original_name,
            "declared_license": self.declared_license,
            "license_status": self.license_status.value,
            "license_confidence": self.license_confidence,
            "redistribution": self.redistribution,
            "required_attribution": self.required_attribution,
            "privacy": self.privacy.classification,
            "high_confidence_pii": self.privacy.high_confidence_count,
            "approved_for_public_release": self.is_approved_for_public_release(),
        }


@dataclass
class LicenseAndPrivacyReport:
    """Aggregated license + privacy report for a set of sources."""

    records: list[SourceLicenseRecord] = field(default_factory=list)

    def add(self, record: SourceLicenseRecord) -> None:
        self.records.append(record)

    @property
    def blocked_count(self) -> int:
        return sum(1 for r in self.records if r.license_status == LicenseStatus.blocked)

    @property
    def review_count(self) -> int:
        return sum(1 for r in self.records if r.license_status == LicenseStatus.review)

    @property
    def allowed_count(self) -> int:
        return sum(1 for r in self.records if r.license_status == LicenseStatus.allowed)

    def unresolved_blocked_sources(self) -> list[str]:
        return [r.original_name for r in self.records if not r.is_approved_for_public_release()]

    def license_summary(self) -> dict[str, Any]:
        # most restrictive status governs the collection
        if any(r.license_status == LicenseStatus.blocked for r in self.records):
            status = LicenseStatus.blocked
        elif any(r.license_status == LicenseStatus.review for r in self.records):
            status = LicenseStatus.review
        else:
            status = LicenseStatus.allowed
        return {
            "status": status.value,
            "count": len(self.records),
            "allowed": self.allowed_count,
            "review": self.review_count,
            "blocked": self.blocked_count,
        }

    def privacy_summary(self) -> dict[str, Any]:
        report = PrivacyReport.from_classifications(
            [(r.source_id, r.privacy) for r in self.records]
        )
        d = report.to_dict()
        d["pii_findings"] = sum(r.privacy.high_confidence_count for r in self.records)
        d["high_confidence"] = d["pii_findings"] > 0
        return d

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources": [r.to_dict() for r in self.records],
            "license": self.license_summary(),
            "privacy": self.privacy_summary(),
            "publication_gate": publication_gate(self),
        }


def publication_gate(report: LicenseAndPrivacyReport) -> dict[str, Any]:
    """Evaluate the §15.6 publication gate over the aggregate report.

    Returns ``{allowed, reason, unresolved}``. Public publication is blocked
    unless every included source has an approved redistribution decision.
    """
    unresolved = report.unresolved_blocked_sources()
    status = report.license_summary()["status"]
    allowed = status == LicenseStatus.allowed.value and not unresolved
    if allowed:
        reason = "all sources approved for redistribution, no blocked or high-confidence-PII source"
    elif report.blocked_count:
        reason = f"{report.blocked_count} source(s) license-blocked"
    elif report.review_count:
        reason = f"{report.review_count} source(s) pending license/redistribution review"
    else:
        reason = f"{len(unresolved)} source(s) not approved for public release"
    return {"allowed": allowed, "reason": reason, "unresolved": unresolved, "status": status}


__all__ = [
    "SourceLicenseRecord",
    "LicenseAndPrivacyReport",
    "publication_gate",
]
