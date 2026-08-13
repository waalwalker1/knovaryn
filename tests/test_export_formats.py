"""Multi-format export tests (spec §15 / WP H4) + A6 provenance gate.

Builds ``TrainingExample`` objects directly (no DB) and calls the pure format
row builders / ``export_format``, asserting required keys and that no line loses
its lineage (``source_document_ids`` / ``source_span_ids`` /
``generation_candidate_ids`` / ``content_hash``) — contract rules 13/14.
"""

from __future__ import annotations

import json

import pytest

from knovaryn.domain.schemas import CanonicalMessage, Topology, TrainingExample
from knovaryn.pipeline.export import exporters
from knovaryn.pipeline.export.formats import (
    SUPPORTED_FORMATS,
    example_row_for,
    export_format,
)
from knovaryn.pipeline.export.gate import recompute_content_hash


def _example(*, ex_id: str = "ex-1", topology: Topology = Topology.sft) -> TrainingExample:
    ex = TrainingExample(
        id=ex_id,
        project_id="p",
        topology=topology,
        system_messages=["You are helpful."],
        prompt_messages=[CanonicalMessage(role="user", content="What is a widget?")],
        chosen_messages=[CanonicalMessage(role="assistant", content="A widget is a part.")],
        rejected_messages=[CanonicalMessage(role="assistant", content="A widget is pie.")],
        source_span_ids=["sp_1"],
        source_document_ids=["src_1"],
        generation_candidate_ids=["cand_1"],
        split="train",
        content_hash="",
    )
    ex.content_hash = recompute_content_hash(ex)
    return ex


def test_every_supported_format_is_registered_and_serializable():
    # a representative example that is not fatal for hash equality
    ex = _example(topology=Topology.sft)
    for fmt in SUPPORTED_FORMATS:
        res = export_format([ex], fmt)
        assert res.rows == 1
        assert res.sha256
        parsed = json.loads(res.bytes.decode("utf-8"))
        assert parsed["source_document_ids"] == ["src_1"]
        assert parsed["source_span_ids"] == ["sp_1"]
        assert parsed["generation_candidate_ids"] == ["cand_1"]
        assert parsed["content_hash"]
        assert "content_hash" in parsed


@pytest.mark.parametrize(
    "fmt,required_key",
    [
        ("openai_chat", "messages"),
        ("sharegpt", "conversations"),
        ("alpaca", "instruction"),
        ("trl_sft", "text"),
        ("trl_preference", "chosen"),
        ("kto", "label"),
        ("evaluation", "reference_answer"),
        ("huggingface_layout", "messages"),
    ],
)
def test_format_required_keys(fmt, required_key):
    ex = _example(topology=Topology.sft)
    row = example_row_for(ex, fmt)
    assert required_key in row
    # lineage always preserved per format (rule 13/14)
    assert row["source_document_ids"] == ["src_1"]
    assert row["content_hash"]


def test_openai_chat_messages_are_wellformed():
    ex = _example(topology=Topology.sft)
    row = example_row_for(ex, "openai_chat")
    roles = [m["role"] for m in row["messages"]]
    assert roles == ["system", "user", "assistant"]
    assert row["messages"][0]["content"] == "You are helpful."


def test_sharegpt_human_gpt_roles():
    ex = _example(topology=Topology.sft)
    row = example_row_for(ex, "sharegpt")
    turn = row["conversations"][0]
    assert turn["from"] == "human"
    assert turn["value"] == "What is a widget?"


def test_unsupported_format_raises():
    ex = _example()
    with pytest.raises(ValueError):
        export_format([ex], "not-a-format")


def test_jsonl_format_delegates_to_base_row():
    ex = _example(topology=Topology.sft)
    row = example_row_for(ex, "jsonl")
    assert row == exporters.example_row(ex)


def test_recompute_content_hash_matches_stored_for_all_topologies():
    for topo in (Topology.sft, Topology.preference, Topology.kto, Topology.evaluation):
        ex = _example(topology=topo)
        assert recompute_content_hash(ex) == ex.content_hash
