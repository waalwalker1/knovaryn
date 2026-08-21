"""Source-group splitting (spec §10.1, §16.1).

Documents are assigned to train/validation/test at the SOURCE-GROUP level
BEFORE generation. Never randomly split examples from the same source/family
across splits. Strategies: grouped_random, time_based, holdout, manual, kfold.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from ..domain.errors import ConfigurationError
from ..domain.schemas import SourceDocument


@dataclass
class SplitAssignment:
    by_source_id: dict[str, str] = field(default_factory=dict)
    groups: dict[str, str] = field(default_factory=dict)  # group_key -> split
    strategy: str = "grouped_random"
    seed: int = 42

    def split_of(self, source_id: str) -> str | None:
        return self.by_source_id.get(source_id)


@dataclass
class SplitIntegrityResult:
    """Leakage check: no source-group may appear in more than one split (WP B2)."""

    ok: bool
    group_count: int = 0
    leaked_groups: list[str] = field(default_factory=list)
    groups_per_split: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "group_count": self.group_count,
            "leaked_groups": self.leaked_groups,
            "groups_per_split": self.groups_per_split,
        }


def check_split_integrity(group_splits: Iterable[tuple[str, str]]) -> SplitIntegrityResult:
    """Return a leakage-free verdict for a stream of ``(group_key, split)`` pairs.

    A single source-group must never be split across train/validation/test; if
    it is, the result is NOT ok and the offending groups are named. Pair this
    over persisted candidate/chunk lineage (which carries explicit
    ``source_group_id`` and ``split``) to prove contamination control.
    """
    seen: dict[str, str] = {}
    per_split: dict[str, int] = {}
    leaked: list[str] = []
    for group, split in group_splits:
        per_split[split] = per_split.get(split, 0) + 1
        if group in seen and seen[group] != split and group not in leaked:
            leaked.append(group)
        seen.setdefault(group, split)
    return SplitIntegrityResult(
        ok=not leaked,
        group_count=len(seen),
        leaked_groups=leaked,
        groups_per_split=per_split,
    )


def _stable_bucket(group_key: str, seed: int, ratios: tuple[float, float]) -> int:
    digest = hashlib.sha256(f"{seed}:{group_key}".encode()).hexdigest()
    r = int(digest[:8], 16) / 0xFFFFFFFF
    train, val = ratios
    if r < train:
        return 0
    if r < train + val:
        return 1
    return 2


def assign_splits(
    sources: list[SourceDocument],
    *,
    strategy: str = "grouped_random",
    train: float = 0.8,
    validation: float = 0.1,
    test: float = 0.1,
    seed: int = 42,
    time_group_key: str | None = None,
    manual: dict[str, str] | None = None,
    k: int = 5,
    fold: int = 0,
) -> SplitAssignment:
    if strategy not in ("grouped_random", "time_based", "holdout", "manual", "kfold"):
        raise ConfigurationError(f"unknown split strategy: {strategy!r}")
    assign = SplitAssignment(strategy=strategy, seed=seed)
    splits = ("train", "validation", "test")
    groups = _collect_groups(sources)

    if strategy == "manual":
        manual = manual or {}
        for src in sources:
            s = manual.get(src.id) or manual.get(src.group_key or "")
            if s not in splits and src.group_key and (src.group_key in manual):
                s = manual[src.group_key]
            assign.by_source_id[src.id] = s if s in splits else "train"
            if src.group_key:
                assign.groups[src.group_key] = assign.by_source_id[src.id]
        return assign

    if strategy == "time_based":
        # chronological: first train, then validation, then test by ordering
        ordered = sorted(sources, key=lambda s: s.acquisition_time)
        total = len(ordered) or 1
        for i, src in enumerate(ordered):
            ratio = i / total
            if ratio < train:
                s = "train"
            elif ratio < train + validation:
                s = "validation"
            else:
                s = "test"
            assign.by_source_id[src.id] = s
            if src.group_key:
                assign.groups[src.group_key] = s
        return assign

    if strategy == "holdout":
        # a specific collection is held out to test
        holdout_group = time_group_key  # reuse parameter as the holdout group key
        if holdout_group:
            for src in sources:
                if src.group_key == holdout_group:
                    assign.by_source_id[src.id] = "test"
                else:
                    assign.by_source_id[src.id] = "train"
                    if src.group_key:
                        assign.groups[src.group_key] = "train"
            return assign

    if strategy == "kfold":
        # assign to a single fold for research manifests; here we build one fold's split
        folds = _kfold_groups(groups, k=k, seed=seed)
        for group_key, gsources in groups.items():
            fold_idx = folds[group_key]
            if fold_idx == fold:
                s = "test"
            elif fold_idx == (fold + 1) % k:
                s = "validation"
            else:
                s = "train"
            for src in gsources:
                assign.by_source_id[src.id] = s
            assign.groups[group_key] = s
        return assign

    # grouped_random (default)
    for group_key, gsources in groups.items():
        idx = _stable_bucket(group_key, seed, (train, validation))
        s = splits[idx]
        for src in gsources:
            assign.by_source_id[src.id] = s
        assign.groups[group_key] = s
    return assign


def _collect_groups(sources: list[SourceDocument]) -> dict[str, list[SourceDocument]]:
    groups: dict[str, list[SourceDocument]] = {}
    for src in sources:
        key = src.group_key or src.id
        groups.setdefault(key, []).append(src)
    return groups


def _kfold_groups(groups: dict[str, list[SourceDocument]], *, k: int, seed: int) -> dict[str, int]:
    rng = random.Random(seed)
    keys = sorted(groups.keys())
    rng.shuffle(keys)
    return {key: i % k for i, key in enumerate(keys)}


# ---------------------------------------------------------------------------
# Split release gate and small-corpus policy (defect 4.5)
# ---------------------------------------------------------------------------


@dataclass
class SplitReleaseGate:
    """Verdict on whether a split configuration is releasable.

    A "normal" training release requires a non-empty train split
    (train_count > 0). Small corpora are governed by an explicit policy that
    may permit train-only *experimental* releases.
    """

    ok: bool
    reason: str = ""
    gate: str = ""  # "train_required" | "small_corpus_policy" | "ok"

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "reason": self.reason, "gate": self.gate}


def evaluate_split_release(
    *,
    train_count: int,
    validation_count: int = 0,
    test_count: int = 0,
    source_group_count: int = 0,
    small_corpus_allowance: bool = False,
) -> SplitReleaseGate:
    """Decide whether a split set may be released (defect 4.5).

    Rules:
    - A normal release requires ``train_count > 0``. An empty train split is a
      hard block: releasing a "training" dataset with no training rows is a
      contradiction (blocked with gate ``train_required``).
    - Small-corpus policy: when the corpus is tiny (few source groups), a
      train-only *experimental* release is permitted only if the caller
      explicitly opts in (``small_corpus_allowance=True``). Without the
      explicit allowance, a train-only split on a tiny corpus is still blocked
      so the policy is never silently assumed.
    """
    if train_count <= 0:
        return SplitReleaseGate(
            ok=False,
            reason=(
                "train split is empty (train_count=0); a training release requires training rows"
            ),
            gate="train_required",
        )

    # Train-only on a small corpus is explicit-experimental only.
    if validation_count <= 0 and test_count <= 0 and source_group_count > 0:
        # 1 group -> train-only; per policy this needs an explicit allowance.
        if source_group_count == 1 and not small_corpus_allowance:
            return SplitReleaseGate(
                ok=False,
                reason=(
                    "single-source-group train-only release requires "
                    "explicit small_corpus_allowance"
                ),
                gate="small_corpus_policy",
            )
        return SplitReleaseGate(
            ok=True,
            reason="train-only split accepted (experimental / explicit small-corpus policy)",
            gate="small_corpus_policy",
        )

    return SplitReleaseGate(ok=True, reason="split set is releasable", gate="ok")


def plan_small_corpus_splits(source_group_count: int) -> dict[str, int]:
    """Return the canonical split set for a given small-corpus size (defect 4.5).

    - 1 source group   -> train only (experimental)
    - 2 source groups  -> train + validation, no test
    - 3+ source groups -> train + validation + test
    """
    if source_group_count <= 1:
        return {"train": 1}
    if source_group_count == 2:
        return {"train": 1, "validation": 1}
    return {"train": 1, "validation": 1, "test": 1}
