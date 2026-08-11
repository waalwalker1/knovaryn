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
    GroundingValidator,
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
        chosen_messages=[CanonicalMessage(role=r, content=c) for r, c in messages if r == "assistant"],
        source_span_ids=span_ids or [],
        topology=topo,
    )


def test_cross_document_contamination_is_rejected():
    """An example citing only Alpha, answering 'amber', must FAIL grounding."""
    ex = _ex([("user", "What does Alpha use?"), ("assistant", "The answer is amber.")],
             span_ids=["span_alpha"])
    ctx = ValidatorContext(source_texts={"span_alpha": ALPHA, "span_beta": BETA})
    grounding = _await(GroundingValidator().assess(ex, ctx))
    assert grounding.status != QualityStatus.accepted, (
        "cross-document answer 'amber' must fail grounding when citing only Alpha"
    )


def test_cited_only_evidence_scope():
    """Grounding must be evaluated against ONLY the cited Alpha span, not Beta."""
    ex = _ex([("user", "What does Alpha use?"), ("assistant", "The answer is amber.")],
             span_ids=["span_alpha"])
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
