"""Unit tests for quality-report aggregation (spec §13.4).

``build_quality_report`` was previously covered only incidentally by full
pipeline runs; the planner's largest-remainder fix shifted generation toward
concentrated compositions and dropped the named-validator aggregation paths
below their documented branch baseline. These tests exercise the contract
directly so the module's coverage no longer depends on incidental generation
patterns.
"""

from __future__ import annotations

from knovaryn.domain.schemas import QualityAssessment, QualityStatus
from knovaryn.pipeline.quality.reports import build_quality_report


def _a(
    example_id: str,
    *,
    validator: str = "overall",
    version: str = "1.0",
    status: QualityStatus = QualityStatus.accepted,
    score: float = 0.9,
) -> QualityAssessment:
    return QualityAssessment(
        id=f"qa_{example_id}_{validator}",
        example_id=example_id,
        validator_name=validator,
        validator_version=version,
        status=status,
        score=score,
    )


class TestEmptyAssessments:
    def test_empty_returns_defaults(self):
        r = build_quality_report([])
        assert r.total_examples == 0
        assert r.status_counts == {}
        assert r.per_validator == {}
        assert r.per_topology == {}
        assert r.mean_overall == 0.0
        assert r.acceptance_rate == 0.0

    def test_empty_report_hash_is_stable(self):
        """report_hash must be a deterministic content hash of the dict form."""
        h1 = build_quality_report([]).report_hash()
        h2 = build_quality_report([]).report_hash()
        assert h1 == h2 and len(h1) >= 32


class TestNamedValidatorAggregation:
    def test_per_validator_buckets_count_sum_mean_and_statuses(self):
        assessments = [
            _a("ex1", validator="claims", score=0.8),
            _a("ex2", validator="claims", score=0.6),
            _a("ex3", validator="claims", status=QualityStatus.review, score=0.4),
        ]
        r = build_quality_report(assessments)
        bucket = r.per_validator["claims"]
        assert bucket["count"] == 3
        assert round(bucket["sum"], 4) == 1.8
        assert bucket["mean"] == 0.6  # rounded mean over count
        assert bucket["accepted"] == 2
        assert bucket["review"] == 1
        # every non-overall validator's version is recorded exactly once per name
        assert r.validator_versions == {"claims": "1.0"}

    def test_validator_versions_keep_latest_per_name(self):
        assessments = [
            _a("ex1", validator="claims", version="1.0"),
            _a("ex2", validator="claims", version="2.0"),
        ]
        r = build_quality_report(assessments)
        assert r.validator_versions == {"claims": "2.0"}

    def test_topologies_breakdown_with_unknown_fallback(self):
        assessments = [
            _a("ex1", validator="claims"),
            _a("ex2", validator="claims"),
        ]
        r = build_quality_report(assessments, topologies={"ex1": "sft"})
        assert r.per_topology["sft"]["total"] == 1
        assert r.per_topology["unknown"]["total"] == 1
        assert r.per_topology["sft"]["accepted"] == 1


class TestOverallAggregates:
    def test_mean_overall_and_acceptance_rate(self):
        assessments = [
            _a("ex1", status=QualityStatus.accepted, score=1.0),
            _a("ex2", status=QualityStatus.review, score=0.5),
        ]
        d = build_quality_report(assessments).to_dict()
        assert d["mean_overall"] == 0.75
        assert d["acceptance_rate"] == 0.5
        assert d["status_counts"] == {"accepted": 1, "review": 1}

    def test_no_overall_entries_keeps_mean_at_zero(self):
        """Only 'overall' rows feed mean_overall; named validators never do."""
        assessments = [_a("ex1", validator="claims", score=0.99)]
        r = build_quality_report(assessments)
        assert r.mean_overall == 0.0
        # acceptance rate still reflects status counts over total
        assert r.acceptance_rate == 1.0
