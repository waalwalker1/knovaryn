"""WP D regression tests: real generation and provider gateway.

Covers the D1–D8 acceptance criteria that the baseline violated:
- D1  versioned prompt rendering (system + user, schema embedded) — never raw-only
- D2  real per-topology output schemas rendered to JSON Schema + local validation
- D3  bounded repair then quarantine of malformed provider output
- D5  no silent fake fallback (live request + no provider = explicit failure)
- D6  full model-call ledger persisted per call
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from knovaryn.domain.errors import ProviderError, UnsupportedOperationError
from knovaryn.infrastructure.models.gateway import ModelGateway
from knovaryn.pipeline.output_schemas import (
    generation_output_schema,
    schema_hash_for,
    supported_topologies,
    validate_generation_output,
)

pytestmark = pytest.mark.unit

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def run(coro):
    return _LOOP.run_until_complete(coro)


def _valid_sft_body() -> dict[str, Any]:
    return {
        "task_family": "factual_explanation",
        "difficulty": "intermediate",
        "messages": [
            {"role": "user", "content": "How is the widget assembled?"},
            {
                "role": "assistant",
                "content": "It is assembled from a base plate and a lid.",
            },
        ],
        "evidence": [],
        "answerability": "answerable",
        "concise_generation_note": "",
    }


# ---------------------------------------------------------------------------
# D2 — structured-output schemas and local validation
# ---------------------------------------------------------------------------


def test_all_topologies_have_schemas() -> None:
    assert supported_topologies() == ["sft", "preference", "kto", "evaluation"]


def test_output_schema_excludes_lineage_fields() -> None:
    for topo in supported_topologies():
        schema = generation_output_schema(topo)
        props = schema.get("properties", {})
        # lineage is stamped by the generator, never demanded of a provider
        for lineage in ("chunk_id", "source_document_id", "source_group_id", "split"):
            assert lineage not in props, f"{topo} schema exposes lineage {lineage}"
        # required set must never include lineage
        assert all(
            f not in schema.get("required", [])
            for f in (
                "chunk_id",
                "source_document_id",
                "source_group_id",
                "split",
                "topology",
            )
        )


def test_schema_hash_is_content_derived_and_stable() -> None:
    h1 = schema_hash_for("sft")
    h2 = schema_hash_for("sft")
    h3 = schema_hash_for("preference")
    assert h1 == h2
    assert h1.startswith("schema:")
    assert h1 != h3  # different topology -> different schema -> different hash
    assert "knovaryn-candidate/v1" not in h1  # old hardcoded marker is gone


def test_validate_output_accepts_valid_sft_body() -> None:
    assert validate_generation_output("sft", _valid_sft_body()) == []


def test_validate_output_rejects_malformed_body() -> None:
    bad = dict(_valid_sft_body())
    bad["messages"] = [{"role": "user", "content": "no assistant turn"}]
    codes = validate_generation_output("sft", bad)
    assert codes, "malformed body must produce schema reason codes"


def test_validate_unknown_topology_raises() -> None:
    with pytest.raises(ProviderError):
        validate_generation_output("bogus", {})


# ---------------------------------------------------------------------------
# D1 — versioned prompt rendering (not raw-only)
# ---------------------------------------------------------------------------


def test_generate_renders_system_and_user_messages() -> None:
    from knovaryn.pipeline.generate import Generator
    from knovaryn.pipeline.planner import AssignmentSpec

    gw = ModelGateway(generator_model="fake")
    gen = Generator(gateway=gw, max_chunks_per_spec=1)
    spec = AssignmentSpec(
        topology="sft",
        task_family="factual_explanation",
        difficulty="intermediate",
        per_chunk=1,
    )
    tpl = gen._template_version(spec)
    # exercise the private renderer directly to assert the prompt shape
    from knovaryn.prompts.library import get_template

    msgs = gen._render_messages(spec, get_template(spec.task_family, spec.topology), "SOME SOURCE")
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    joined = "\n".join(m["content"] for m in msgs)
    # versioned template + source-as-data boundary, not raw text alone
    assert "source material" in joined.lower()
    assert "TASK_FAMILY" in joined
    assert "DIFFICULTY" in joined
    assert "schema" in joined.lower()
    assert "SOME SOURCE" in joined
    assert tpl == "1"


# ---------------------------------------------------------------------------
# D5 — no silent fake fallback
# ---------------------------------------------------------------------------


def test_fake_request_uses_fake() -> None:
    gw = ModelGateway()  # no real provider
    result = run(
        gw.generate(
            prompt_template_version="1",
            sampling={"temperature": 0.3},
            schema_hash="s",
            source_hashes=[],
            messages=[{"role": "user", "content": "x"}],
            source_text="Enough repeated source material for a sentence.",
            mode="sft",
            task_family="factual_explanation",
            model="fake",
        )
    )
    assert result.get("model") == "fake"


def test_default_generator_model_is_fake() -> None:
    gw = ModelGateway()
    result = run(
        gw.generate(
            prompt_template_version="1",
            sampling={"temperature": 0.3},
            schema_hash="s",
            source_hashes=[],
            messages=[{"role": "user", "content": "x"}],
            source_text="Enough repeated source material for a sentence.",
            mode="sft",
            task_family="factual_explanation",
            model=None,
        )
    )
    assert result.get("model") == "fake"


def test_live_request_without_provider_fails_loudly() -> None:
    gw = ModelGateway()  # no real provider configured
    with pytest.raises(UnsupportedOperationError):
        run(
            gw.generate(
                prompt_template_version="1",
                sampling={"temperature": 0.3},
                schema_hash="s",
                source_hashes=[],
                messages=[{"role": "user", "content": "x"}],
                source_text="Enough repeated source material for a sentence.",
                mode="sft",
                task_family="factual_explanation",
                model="deepseek-v4-flash",
            )
        )


class _FakeRealProvider:
    """A minimal live provider for resolution tests."""

    name = "litellm"

    async def complete(self, **kwargs: Any) -> dict[str, Any]:
        return {"content": {"text": "hi"}, "usage": {}, "model": kwargs.get("model", "")}


def test_live_request_with_provider_uses_live() -> None:
    gw = ModelGateway(real_provider=_FakeRealProvider(), generator_model="deepseek-v4-flash")
    result = run(
        gw.generate(
            prompt_template_version="1",
            sampling={"temperature": 0.3},
            schema_hash="s",
            source_hashes=[],
            messages=[{"role": "user", "content": "x"}],
            mode="sft",
            model="deepseek-v4-flash",
        )
    )
    assert result.get("_fingerprint")


# ---------------------------------------------------------------------------
# D6 — full model-call ledger
# ---------------------------------------------------------------------------


class _RecordingCallRepo:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def record(self, call: dict[str, Any]) -> None:
        self.calls.append(dict(call))


def test_gateway_records_full_model_call_ledger() -> None:
    repo = _RecordingCallRepo()
    gw = ModelGateway(
        generator_model="fake",
        project_id="proj_x",
        job_id="job_1",
        stage="generate",
        profile="fake",
        model_call_repo=repo,
    )
    run(
        gw.generate(
            prompt_template_version="v1",
            sampling={"temperature": 0.3, "max_output_tokens": 100},
            schema_hash="schema:abc",
            source_hashes=["h1"],
            messages=[{"role": "user", "content": "x"}],
            source_text="Enough repeated source material for a sentence.",
            mode="sft",
            task_family="factual_explanation",
            model="fake",
        )
    )
    assert len(repo.calls) == 1
    call = repo.calls[0]
    assert call["job_id"] == "job_1"
    assert call["project_id"] == "proj_x"
    assert call["stage"] == "generate"
    assert call["provider"] == "fake"
    assert call["requested_model"] == "fake"
    assert call["resolved_model"] == "fake"
    assert call["profile"] == "fake"
    assert call["prompt_template_hash"] == "v1"
    assert call["schema_hash"] == "schema:abc"
    assert call["request_fingerprint"]
    assert call["sampling_params"] == {"temperature": 0.3, "max_output_tokens": 100}
    assert isinstance(call["estimated_cost"], float)
    assert isinstance(call["latency_ms"], int)
    assert call["status"] == "ok"
    assert call["retry_count"] == 0


# ---------------------------------------------------------------------------
# D3 — bounded repair then quarantine of malformed provider output
# ---------------------------------------------------------------------------


class _MalformedProvider:
    """Always returns a body that fails the sft schema (no assistant turn)."""

    name = "fake"

    async def complete(self, **kwargs: Any) -> dict[str, Any]:
        body = _valid_sft_body()
        body["messages"] = [{"role": "user", "content": "no assistant"}]
        return {"content": body, "usage": {}, "model": "fake"}


def test_generator_quarantines_persistently_malformed_output() -> None:
    from knovaryn.pipeline.generate import Generator
    from knovaryn.pipeline.planner import AssignmentSpec, PlanResult

    gw = ModelGateway(generator_model="fake", fake=_MalformedProvider())  # bypass FakeProvider
    gen = Generator(
        gateway=gw,
        max_chunks_per_spec=2,
        max_repair_attempts=1,
    )

    class _Chunk:
        id = "chunk_1"
        sha256 = "h1"
        main_text = "Enough repeated source material for a sentence."
        source_document_id = "src_1"
        source_group_id = None
        source_span_ids = ["span_1"]
        split = "train"

    spec = AssignmentSpec(
        topology="sft",
        task_family="factual_explanation",
        difficulty="intermediate",
        per_chunk=2,
    )
    plan = PlanResult(specs=[spec])

    outcome = run(
        gen.generate_for_plan(
            chunks=[_Chunk()],
            plan=plan,
            seed_base=1,
        )
    )
    # D3: malformed output is quarantined — recorded as an error, never emitted
    assert outcome.candidates_generated == 0
    assert outcome.errors, "persistently malformed output must be quarantined with an error"
    assert any("schema validation" in e for e in outcome.errors)
