"""Quality validation (spec §13, §14)."""

from __future__ import annotations

from knovaryn.domain.schemas import CanonicalMessage, QualityStatus, Topology, TrainingExample
from knovaryn.infrastructure.models.fake_provider import FakeProvider
from knovaryn.pipeline.quality.validators import (
    GroundingValidator,
    ValidatorContext,
    assemble_decision,
)


def _sft_example() -> TrainingExample:
    return TrainingExample(
        id="ex1",
        project_id="p",
        topology=Topology.sft,
        system_messages=["You are a careful assistant."],
        prompt_messages=[CanonicalMessage(role="user", content="Summarize the lifecycle.")],
        chosen_messages=[CanonicalMessage(role="assistant", content="Data preparation comes first, then training, then evaluation.")],
        source_span_ids=["span1"],
    )


def test_grounding_validator_accepts_grounded_answer() -> None:
    ex = _sft_example()
    ctx = ValidatorContext(source_texts={"span1": "Data preparation comes first. Then model training. Then evaluation."})
    assessment = __import__("asyncio").run(GroundingValidator().assess(ex, ctx))
    assert assessment.score >= 0.4


def test_assemble_decision_returns_overall() -> None:
    ex = _sft_example()
    ctx = ValidatorContext(source_texts={"span1": "Data preparation comes first. Then model training. Then evaluation."})
    import asyncio

    grounding = asyncio.run(GroundingValidator().assess(ex, ctx))
    from knovaryn.pipeline.quality.validators import CompletenessValidator, FormatValidator, RefusalValidator

    complete = asyncio.run(CompletenessValidator().assess(ex, ctx))
    fmt = asyncio.run(FormatValidator().assess(ex, ctx))
    refusal = asyncio.run(RefusalValidator().assess(ex, ctx))
    overall = assemble_decision([grounding, complete, fmt, refusal], example_id=ex.id, is_preference=False)
    assert overall.validator_name == "overall"
    assert overall.status in (QualityStatus.accepted, QualityStatus.review, QualityStatus.rejected)


def test_fake_provider_produces_deterministic_sft() -> None:
    provider = FakeProvider()
    import asyncio

    out = asyncio.run(
        provider.complete(
            messages=[{"role": "user", "content": "q"}],
            source_text="The lifecycle begins with data preparation. Next model training occurs.",
            chunk_id="ck123",
            source_span_ids=["s1"],
            task_family="factual_explanation",
            difficulty="intermediate",
            mode="sft",
        )
    )
    body = out["content"]
    assert body["answerability"] == "answerable"
    assert body["task_family"] == "factual_explanation"
    # deterministic: same inputs -> same output
    out2 = asyncio.run(
        provider.complete(
            messages=[{"role": "user", "content": "q"}],
            source_text="The lifecycle begins with data preparation. Next model training occurs.",
            chunk_id="ck123",
            source_span_ids=["s1"],
            task_family="factual_explanation",
            difficulty="intermediate",
            mode="sft",
        )
    )
    assert out["content"] == out2["content"]
