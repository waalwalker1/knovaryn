"""Regression tests: small corpus policy (defect 4.5).

Small corpus rules for splits, plus source-group-level leakage integrity.
"""

from knovaryn.pipeline.split import (
    check_split_integrity,
    evaluate_split_release,
    plan_small_corpus_splits,
)


class TestSmallCorpusPolicy:
    """Small corpus rules for splits."""

    def test_single_group_train_only(self):
        """1 source group produces train-only experimental release."""
        splits = plan_small_corpus_splits(1)
        assert splits == {"train": 1}, splits
        gate = evaluate_split_release(
            train_count=25,
            validation_count=0,
            test_count=0,
            source_group_count=1,
        )
        assert gate.gate == "small_corpus_policy", gate.to_dict()

    def test_two_groups_train_validation(self):
        """2 source groups produce train + validation, no test."""
        splits = plan_small_corpus_splits(2)
        assert "train" in splits and "validation" in splits, splits
        assert "test" not in splits, splits

    def test_three_groups_train_val_test(self):
        """3+ source groups produce train + val + test."""
        splits = plan_small_corpus_splits(3)
        assert splits == {"train": 1, "validation": 1, "test": 1}, splits
        splits4 = plan_small_corpus_splits(4)
        assert "test" in splits4, splits4

    def test_group_level_integrity(self):
        """No single source-group may leak across splits."""
        result = check_split_integrity(
            [("g1", "train"), ("g1", "train"), ("g2", "validation"), ("g1", "test")]
        )
        assert result.ok is False, result.to_dict()
        assert "g1" in result.leaked_groups, result.to_dict()

        clean = check_split_integrity([("g1", "train"), ("g2", "validation"), ("g3", "test")])
        assert clean.ok is True, clean.to_dict()
