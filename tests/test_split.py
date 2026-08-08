"""Source-group splitting (spec §10.1, §16.1).

A source group (family / document collection) must be assigned to exactly one
split — never split examples from the same source across train/validation/test.
"""

from __future__ import annotations

from knovaryn.domain.schemas import SourceDocument, SourceKind
from knovaryn.pipeline.split import assign_splits


def _src(sid: str, group: str) -> SourceDocument:
    return SourceDocument(
        id=sid,
        project_id="p",
        original_name=sid,
        media_type="text/plain",
        byte_size=10,
        sha256=sid,
        source_kind=SourceKind.upload,
        group_key=group,
    )


def test_grouped_random_never_splits_a_source_group() -> None:
    sources = [_src(f"s{i}", "family_docs") for i in range(20)]
    assign = assign_splits(sources, strategy="grouped_random", seed=42)
    seen = {assign.split_of(s.id) for s in sources}
    assert len(seen) == 1, f"same source-group must land in a single split, got {seen}"


def test_distinct_groups_can_land_in_any_split() -> None:
    sources = [
        SourceDocument(
            id=f"s{n}", project_id="p", original_name=f"s{n}", media_type="text/plain",
            byte_size=1, sha256=f"s{n}", source_kind=SourceKind.upload, group_key=g,
        )
        for n, g in enumerate(f"g{i}" for i in range(6))
    ]
    assign = assign_splits(sources, strategy="grouped_random", seed=1)
    splits = {assign.split_of(s.id) for s in sources}
    assert splits <= {"train", "validation", "test"}


def test_manual_override() -> None:
    sources = [_src("a", "g1"), _src("b", "g1"), _src("c", "g2")]
    assign = assign_splits(sources, strategy="manual", manual={"g1": "test", "g2": "train"})
    assert assign.split_of("a") == "test"
    assert assign.split_of("b") == "test"
    assert assign.split_of("c") == "train"


def test_kfold_single_fold_valid_splits() -> None:
    sources = [_src(f"s{i}", f"g{i}") for i in range(10)]
    assign = assign_splits(sources, strategy="kfold", k=5, fold=0)
    for s in sources:
        assert assign.split_of(s.id) in ("train", "validation", "test")
