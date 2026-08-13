"""P0-3/P0-4 regression: evidence-scoped, fail-closed quality engine
(contract §4 P0-3, P0-4; §8 C1-C3; §21.2).

These tests fail on the baseline because:
- grounding is computed over ALL context spans, not just the cited spans (P0-3);
- missing preference signal is set to 1.0 in assemble_decision (P0-4);
- completeness is a length ratio; format is non-emptiness (P0-4);
- there is no three-state verified/unverified/failed model and no contradiction
  validator (P0-4).
"""

from __future__ import annotations

import asyncio

import pytest

from knovaryn.domain.schemas import (
    CanonicalMessage,
    QualityStatus,
    TrainingExample,
)
from knovaryn.pipeline.quality.validators import (
    AnswerabilityValidator,
    CompletenessValidator,
    GroundingValidator,
    SchemaValidator,
    ValidatorContext,
    assemble_decision,
)

pytestmark = pytest.mark.unit

ALPHA = "Alpha protocol uses cobalt keys."
BETA = "Beta protocol uses amber keys."


def _await(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _ex(messages, *, id="ex_1", span_ids=None, topo="sft"):
    return TrainingExample(
        id=id,
        project_id="proj_y",
        prompt_messages=[CanonicalMessage(role=r, content=c) for r, c in messages if r == "user"],
        chosen_messages=[
            CanonicalMessage(role=r, content=c) for r, c in messages if r == "assistant"
        ],
        source_span_ids=span_ids or [],
        topology=topo,
    )


def test_cross_document_contamination_is_rejected():
    """An example citing only Alpha, answering 'amber', must FAIL grounding."""
    ex = _ex(
        [("user", "What does Alpha use?"), ("assistant", "The answer is amber.")],
        span_ids=["span_alpha"],
    )
    ctx = ValidatorContext(source_texts={"span_alpha": ALPHA, "span_beta": BETA})
    grounding = _await(GroundingValidator().assess(ex, ctx))
    assert grounding.status != QualityStatus.accepted, (
        "cross-document answer 'amber' must fail grounding when citing only Alpha"
    )


def test_cited_only_evidence_scope():
    """Grounding must be evaluated against ONLY the cited Alpha span, not Beta."""
    ex = _ex(
        [("user", "What does Alpha use?"), ("assistant", "The answer is amber.")],
        span_ids=["span_alpha"],
    )
    ctx = ValidatorContext(source_texts={"span_alpha": ALPHA, "span_beta": BETA})
    grounding = _await(GroundingValidator().assess(ex, ctx))
    assert grounding.score < 0.6  # with only Alpha cited, amber is ungrounded


def test_missing_preference_signal_must_not_be_accepted():
    """A preference example with no pairwise judgment must not be silently accepted."""
    ex = _ex(
        [("user", "pick the better answer"), ("assistant", "first"), ("assistant", "second")],
        topo="preference",
    )
    ctx = ValidatorContext(source_texts={})
    grounding = _await(GroundingValidator().assess(ex, ctx))
    overall = assemble_decision([grounding], example_id=ex.id, is_preference=True)
    assert overall.status != QualityStatus.accepted, (
        "preference example with no pairwise judgment must not be accepted"
    )


def test_wrong_number_fails_grounding():
    ex = _ex(
        [("user", "How long does assembly take?"), ("assistant", "About five minutes per unit.")],
        span_ids=["span_a"],
    )
    ctx = ValidatorContext(source_texts={"span_a": "Assembly takes about three minutes per unit."})
    grounding = _await(GroundingValidator().assess(ex, ctx))
    assert grounding.score < 0.6, "wrong number must fail grounding"


# --- WP C1/C3.1/C3.5/C4: three-state verification + new validators ------------


def test_schema_validator_rejects_unresolved_evidence():
    """C3.1/C3.2: a cited span that does not resolve must fail schema, never pass."""
    from knovaryn.domain.schemas import CanonicalMessage
    from knovaryn.pipeline.quality.validators import SchemaValidator

    ex = TrainingExample(
        id="ex_s",
        project_id="p",
        topology="sft",
        prompt_messages=[CanonicalMessage(role="user", content="Tell me about X.")],
        chosen_messages=[CanonicalMessage(role="assistant", content="X is described here.")],
        source_span_ids=["missing_span"],
    )
    assessment = _await(SchemaValidator().assess(ex, ValidatorContext(source_texts={})))
    assert assessment.score == 0.0
    assert assessment.verify_state.value == "failed"
    assert "unresolved_evidence" in assessment.reason_codes


def test_schema_validator_requires_evidence():
    from knovaryn.domain.schemas import CanonicalMessage
    from knovaryn.pipeline.quality.validators import SchemaValidator

    ex = TrainingExample(
        id="ex_n",
        project_id="p",
        topology="sft",
        prompt_messages=[CanonicalMessage(role="user", content="Tell me about X.")],
        chosen_messages=[CanonicalMessage(role="assistant", content="X is described here.")],
        source_span_ids=[],
    )
    assessment = _await(SchemaValidator().assess(ex, ValidatorContext(source_texts={})))
    assert "no_evidence" in assessment.reason_codes
    assert assessment.verify_state.value == "failed"


def test_answerability_false_refusal_is_defect():
    """C3.5: refusing while the cited evidence does answer is a false refusal."""
    from knovaryn.domain.schemas import CanonicalMessage, Topology
    from knovaryn.pipeline.quality.validators import AnswerabilityValidator

    ex = TrainingExample(
        id="ex_r",
        project_id="p",
        topology=Topology.sft,
        prompt_messages=[CanonicalMessage(role="user", content="What does Alpha use?")],
        chosen_messages=[
            CanonicalMessage(role="assistant", content="I cannot answer that question.")
        ],
        source_span_ids=["span_alpha"],
    )
    ctx = ValidatorContext(source_texts={"span_alpha": "Alpha protocol uses cobalt keys."})
    assessment = _await(AnswerabilityValidator().assess(ex, ctx))
    assert assessment.score < 0.5
    assert "false_refusal" in assessment.reason_codes


def test_assemble_decision_three_state_c4():
    """C4: a critical dimension left unverified forces review, never acceptance."""
    from knovaryn.pipeline.quality.validators import (
        AnswerabilityValidator,
        SchemaValidator,
    )

    ex = _ex(
        [("user", "What does Alpha use?"), ("assistant", "Alpha uses cobalt keys.")],
        span_ids=["span_alpha"],
    )
    ctx = ValidatorContext(source_texts={"span_alpha": ALPHA})
    grounding = _await(GroundingValidator().assess(ex, ctx))
    # no schema/answerability produced: they are critical and unverified -> review
    overall = assemble_decision([grounding], example_id=ex.id, is_preference=False)
    assert overall.status == QualityStatus.review
    assert any("critical_unverified" in c for c in overall.reason_codes)

    # adding schema + answerability but with schema failed -> rejected
    schema = _await(SchemaValidator().assess(ex, ValidatorContext(source_texts={})))
    ans = _await(AnswerabilityValidator().assess(ex, ctx))
    overall2 = assemble_decision([grounding, schema, ans], example_id=ex.id, is_preference=False)
    assert overall2.status == QualityStatus.rejected
    assert any("critical_failed" in c for c in overall2.reason_codes)


def test_acceptance_requires_all_critical_verified_certifiable():
    """When completeness is verified it certifies instruction_fulfilment (C4)."""
    ex = _ex(
        [("user", "What does Alpha use?"), ("assistant", "Alpha uses cobalt keys.")],
        span_ids=["span_alpha"],
    )
    ctx = ValidatorContext(source_texts={"span_alpha": ALPHA})
    grounding = _await(GroundingValidator().assess(ex, ctx))
    complete = _await(CompletenessValidator().assess(ex, ctx))
    schema = _await(SchemaValidator().assess(ex, ctx))
    ans = _await(AnswerabilityValidator().assess(ex, ctx))
    overall = assemble_decision(
        [grounding, complete, schema, ans], example_id=ex.id, is_preference=False
    )
    # all critical dimensions certified; acceptance then hinges on the policy ceiling
    assert overall.status in (QualityStatus.accepted, QualityStatus.review)
    assert overall.verify_state.value in ("verified", "failed")


def test_pipeline_persists_durable_verify_metadata():
    """WP C1: accepted examples carry durable three-state verification evidence."""
    from knovaryn.application.service import ProjectService
    from knovaryn.domain.schemas import DatasetPlan, Project, SourceDocument

    proj = Project(id="proj_w", slug="w", display_name="W", owner_principal="t")
    srcs = [
        SourceDocument(
            id="s1",
            project_id="proj_w",
            original_name="a.md",
            media_type="text/markdown",
            byte_size=1,
            sha256="h1",
            group_key="g1",
        ),
        SourceDocument(
            id="s2",
            project_id="proj_w",
            original_name="b.md",
            media_type="text/markdown",
            byte_size=1,
            sha256="h2",
            group_key="g2",
        ),
    ]
    contents = [
        "Alpha protocol uses cobalt keys. Repeated material.",
        "Beta protocol uses amber keys. Different material.",
    ]
    r = _await(
        ProjectService().run_pipeline(
            project=proj,
            sources=srcs,
            contents=contents,
            plan=DatasetPlan(task_family_proportions={"factual_explanation": 1.0}),
        )
    )
    assert r.examples, "pipeline must accept at least one grounded example"
    for ex in r.examples:
        verify = ex.private_audit_metadata.get("quality_verify")
        assert verify is not None, "each accepted example must carry quality_verify"
        assert verify["verify_state"] in ("verified", "failed", "unverified")
        # critical dimensions (grounding/schema/answerability/instruction) all verified
        per_dim = verify["per_dimension"]
        for dim in ("grounding", "schema", "answerability", "instruction_fulfillment"):
            assert per_dim.get(dim) == "verified", (
                f"accepted example must have {dim} verified, got {per_dim.get(dim)}"
            )
