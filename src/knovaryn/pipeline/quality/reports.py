"""Quality reports (spec §13.4).

Aggregate per-example assessments into a dataset-level quality report: status
counts, per-validator score distributions, per-topology breakdown, and a
cumulative PII/license summary. Deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...domain.hashing import ContentHasher
from ...domain.schemas import QualityAssessment


@dataclass
class QualityReport:
    total_examples: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    per_validator: dict[str, dict[str, float]] = field(default_factory=dict)
    per_topology: dict[str, dict[str, int]] = field(default_factory=dict)
    mean_overall: float = 0.0
    acceptance_rate: float = 0.0
    validator_versions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_examples": self.total_examples,
            "status_counts": self.status_counts,
            "per_validator": self.per_validator,
            "per_topology": self.per_topology,
            "mean_overall": round(self.mean_overall, 4),
            "acceptance_rate": round(self.acceptance_rate, 4),
            "validator_versions": self.validator_versions,
        }

    def report_hash(self) -> str:
        return ContentHasher.cfg_hash(self.to_dict())


def build_quality_report(assessments: list[QualityAssessment], *, topologies: dict[str, str] | None = None) -> QualityReport:
    report = QualityReport()
    if not assessments:
        return report
    report.total_examples = len(assessments)
    overall_scores: list[float] = []
    topologies = topologies or {}

    for a in assessments:
        report.status_counts[a.status.value] = report.status_counts.get(a.status.value, 0) + 1
        dims = a.evidence.get("per_validator", {}) if isinstance(a.evidence, dict) else {}
        if a.validator_name == "overall":
            overall_scores.append(a.score)
        else:
            bucket = report.per_validator.setdefault(a.validator_name, {})
            bucket["count"] = bucket.get("count", 0) + 1
            bucket["sum"] = bucket.get("sum", 0.0) + a.score
            _bump(bucket, a.status.value)
        if a.validator_name != "overall":
            report.validator_versions[a.validator_name] = a.validator_version

        topo = topologies.get(a.example_id, "unknown")
        t = report.per_topology.setdefault(topo, {})
        t["total"] = t.get("total", 0) + 1
        _bump(t, a.status.value)

    for name, bucket in report.per_validator.items():
        if bucket.get("count"):
            bucket["mean"] = round(bucket["sum"] / bucket["count"], 4)

    if overall_scores:
        report.mean_overall = sum(overall_scores) / len(overall_scores)
    accepted = report.status_counts.get("accepted", 0)
    report.acceptance_rate = accepted / max(report.total_examples, 1)
    return report


def _bump(bucket: dict[str, int], key: str) -> None:
    bucket[key] = bucket.get(key, 0) + 1
