"""Exporters and release bundles (spec §15)."""

from __future__ import annotations

import json

from knovaryn.domain.schemas import CanonicalMessage, QualityStatus, Topology, TrainingExample
from knovaryn.pipeline.export.exporters import example_row, export_jsonl
from knovaryn.pipeline.export.release import build_release_bundle


def _ex(topology: Topology) -> TrainingExample:
    if topology == Topology.preference:
        return TrainingExample(
            id="ex-p",
            project_id="p",
            topology=Topology.preference,
            quality_status=QualityStatus.accepted,
            prompt_messages=[CanonicalMessage(role="user", content="q")],
            chosen_messages=[CanonicalMessage(role="assistant", content="good")],
            rejected_messages=[CanonicalMessage(role="assistant", content="bad")],
            split="train",
        )
    return TrainingExample(
        id="ex-s",
        project_id="p",
        topology=Topology.sft,
        quality_status=QualityStatus.accepted,
        system_messages=["be careful"],
        prompt_messages=[CanonicalMessage(role="user", content="q")],
        chosen_messages=[CanonicalMessage(role="assistant", content="a")],
        split="train",
    )


def test_jsonl_export_rows_are_json() -> None:
    res = export_jsonl([_ex(Topology.sft), _ex(Topology.preference)], path="")
    assert res.rows == 2
    lines = res.bytes.decode("utf-8").splitlines()
    obj = json.loads(lines[0])
    assert "messages" in obj
    assert obj["topology"] == "sft"


def test_preference_row_has_chosen_rejected() -> None:
    row = example_row(_ex(Topology.preference))
    assert "chosen" in row
    assert "rejected" in row
    assert row["topology"] == "preference"


def test_release_bundle_produces_zip_and_hash() -> None:
    split_files = {"train": b"line1\nline2\n", "validation": b"", "test": b""}
    bundle = build_release_bundle(
        version="0.1.0",
        project_id="p",
        session_note="test",
        split_files=split_files,
        dataset_card={"name": "x"},
        quality_report={"status_counts": {}},
        license_summary={},
        privacy_summary={},
        source_manifest={},
        readme="# x",
    )
    assert bundle.byte_size() > 0
    assert len(bundle.sha256()) == 64
    assert "data/train.jsonl" in bundle.files


def test_export_carries_resolvable_provenance() -> None:
    """Every exported row must resolve to its real SourceDocument + candidate (P0-1/WP A).

    source_document_ids, source_span_ids and generation_candidate_ids are
    explicit lineage that consumers (and the provenance-check) rely on.
    """
    ex = TrainingExample(
        id="ex-lineaged",
        project_id="p",
        topology=Topology.sft,
        quality_status=QualityStatus.accepted,
        system_messages=["be careful"],
        prompt_messages=[CanonicalMessage(role="user", content="q")],
        chosen_messages=[CanonicalMessage(role="assistant", content="a")],
        source_document_ids=["src_1"],
        source_span_ids=["sp_1"],
        generation_candidate_ids=["cand_1"],
        content_hash="abc",
        split="train",
    )
    for topo in (Topology.sft, Topology.preference, Topology.kto):
        e = ex.model_copy(update={"id": f"ex-{topo.value}", "topology": topo})
        row = example_row(e)
        assert row["source_document_ids"] == ["src_1"], topo
        assert row["source_span_ids"] == ["sp_1"], topo
        assert row["generation_candidate_ids"] == ["cand_1"], topo
