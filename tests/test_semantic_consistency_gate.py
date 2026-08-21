"""Product-path regression tests for the semantic-consistency gate (defect 4.1).

The deterministic semantic verifier (claims.py / semantic.py) originally
shipped as tested library code that no product path ever called — the
coverage gate caught the orphans. These tests exercise the REAL acceptance
path: ``default_validators()`` (the same factory workspace.py and service.py
call) folded through ``assemble_decision``. Each contradiction class must
force an overall REJECTION via the critical ``semantic_consistency``
dimension, and a faithful answer must still pass.
"""

from __future__ import annotations

import asyncio

from knovaryn.application.service import _artifact_assessment
from knovaryn.domain.schemas import CanonicalMessage, QualityStatus, Topology, TrainingExample
from knovaryn.pipeline.quality import diagnose_example
from knovaryn.pipeline.quality.validators import (
    ValidatorContext,
    assemble_decision,
    default_validators,
)


def _example(answer: str) -> TrainingExample:
    return TrainingExample(
        id="ex-sem",
        project_id="p",
        topology=Topology.sft,
        system_messages=["You are a careful assistant."],
        prompt_messages=[CanonicalMessage(role="user", content="Explain the finding.")],
        chosen_messages=[CanonicalMessage(role="assistant", content=answer)],
        source_span_ids=["span1"],
    )


async def _decide(answer: str, evidence: str, *, cite: bool = True):
    # Exactly the production fold (workspace.py / service.py): the canonical
    # validator set plus the artifact-resistance diagnostic.
    ex = _example(answer)
    ctx = ValidatorContext(source_texts={"span1": evidence} if cite else {})
    decisions = [await v.assess(ex, ctx) for v in default_validators()] + [
        _artifact_assessment(ex, diagnose_example(ex))
    ]
    return assemble_decision(decisions, example_id=ex.id, is_preference=False), decisions


def _semantic(decisions):
    return next(d for d in decisions if d.validator_name == "semantic_consistency")


def test_default_validator_set_includes_semantic_gate() -> None:
    """Guard against silent removal: the factory IS the production set."""
    names = [v.name for v in default_validators()]
    assert "semantic_consistency" in names


def test_causal_reversal_rejected_end_to_end() -> None:
    """Evidence 'shutdown causes alarm', answer 'alarm causes shutdown' → reject."""
    overall, decisions = asyncio.run(
        _decide(
            "The alarm causes the shutdown.",
            "The shutdown causes the alarm.",
        )
    )
    assert overall.status == QualityStatus.rejected
    assert "critical_failed:semantic_consistency" in overall.reason_codes
    assert "causal_direction_reversal" in overall.reason_codes
    assert _semantic(decisions).score == 0.0


def test_number_mismatch_rejected_end_to_end() -> None:
    overall, decisions = asyncio.run(
        _decide(
            "The maximum batch size is 46 records.",
            "The maximum batch size is 64 records.",
        )
    )
    assert overall.status == QualityStatus.rejected
    assert "critical_failed:semantic_consistency" in overall.reason_codes
    assert any(rc.startswith("number_mismatch") for rc in overall.reason_codes)
    assert _semantic(decisions).score == 0.0


def test_negation_flip_rejected_end_to_end() -> None:
    overall, decisions = asyncio.run(
        _decide(
            "The policy permits external publication.",
            "The policy does not permit external publication.",
        )
    )
    assert overall.status == QualityStatus.rejected
    assert "critical_failed:semantic_consistency" in overall.reason_codes
    assert _semantic(decisions).score == 0.0


def test_entity_role_reversal_rejected_end_to_end() -> None:
    overall, decisions = asyncio.run(
        _decide(
            "Alice approved Bob.",
            "Bob approved Alice.",
        )
    )
    assert overall.status == QualityStatus.rejected
    assert "critical_failed:semantic_consistency" in overall.reason_codes
    assert "subject_object_reversal" in overall.reason_codes
    assert _semantic(decisions).score == 0.0


def test_faithful_answer_still_accepted() -> None:
    """No false positives: a claim entailed by its evidence passes every gate."""
    overall, decisions = asyncio.run(
        _decide(
            "Data preparation comes first, then training, then evaluation.",
            "Data preparation comes first. Then model training. Then evaluation.",
        )
    )
    sem = _semantic(decisions)
    assert sem.score == 1.0
    assert sem.verify_state.value == "verified"
    assert overall.status == QualityStatus.accepted


def test_no_cited_evidence_fails_closed() -> None:
    """Nothing cited = nothing verifiable: reject, mirroring grounding."""
    overall, decisions = asyncio.run(_decide("Any answer at all.", "irrelevant", cite=False))
    assert overall.status == QualityStatus.rejected
    assert "no_cited_evidence" in _semantic(decisions).reason_codes
