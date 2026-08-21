"""Regression tests: non-empty training split gate (defect 4.5).

A normal training release requires a non-empty train split; small-corpus
releases are governed by an explicit policy.
"""

from knovaryn.pipeline.split import (
    evaluate_split_release,
)


class TestNonemptyTrainGate:
    """Normal training release requires non-empty train split."""

    def test_nonempty_train_required(self):
        """Release must be blocked when train_count = 0."""
        gate = evaluate_split_release(
            train_count=0,
            validation_count=10,
            test_count=5,
            source_group_count=4,
        )
        assert gate.ok is False, gate.to_dict()
        assert gate.gate == "train_required", gate.to_dict()

    def test_normal_release_accepted(self):
        """A release with a non-empty train split passes the gate."""
        gate = evaluate_split_release(
            train_count=120,
            validation_count=20,
            test_count=15,
            source_group_count=4,
        )
        assert gate.ok is True, gate.to_dict()

    def test_small_corpus_allowance(self):
        """Small corpus policy must be explicit — train-only is not silent."""
        # 1 source group, train-only, NO explicit allowance -> blocked
        gate = evaluate_split_release(
            train_count=30,
            validation_count=0,
            test_count=0,
            source_group_count=1,
            small_corpus_allowance=False,
        )
        assert gate.ok is False, gate.to_dict()
        assert gate.gate == "small_corpus_policy", gate.to_dict()

        # With explicit allowance -> train-only experimental release permitted
        gate2 = evaluate_split_release(
            train_count=30,
            validation_count=0,
            test_count=0,
            source_group_count=1,
            small_corpus_allowance=True,
        )
        assert gate2.ok is True, gate2.to_dict()
