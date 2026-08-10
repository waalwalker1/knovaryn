"""Source-group splitting (spec §10.1, §16.1).

Documents are assigned to train/validation/test at the SOURCE-GROUP level
BEFORE generation. Never randomly split examples from the same source/family
across splits. Strategies: grouped_random, time_based, holdout, manual, kfold.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field

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
