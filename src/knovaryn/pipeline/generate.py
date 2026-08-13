"""Generation stage (spec §12.5/§12.6).

Turns source chunks into generated candidates (SFT / preference / KTO /
evaluation) by invoking the model gateway with versioned prompt templates and
recording a prompt manifest for auditability. Deterministic under the fake
provider; cancel-safe and idempotent via the incoming ``StageContext``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, cast

from ..domain.errors import ProviderError
from ..domain.schemas import (
    CanonicalMessage,
    EvidenceRef,
    GeneratedBatch,
    GeneratedEvaluationCandidate,
    GeneratedKTOCandidate,
    GeneratedPreferenceCandidate,
    GeneratedSFTCandidate,
    SupportType,
)
from ..prompts.library import TemplateRef, get_template, render
from ..prompts.manifest import PromptManifest, build_prompt_usage_record
from .output_schemas import (
    encode_schema_for_wire,
    schema_hash_for,
    validate_generation_output,
)
from .planner import AssignmentSpec, PlanResult

_TOPOLOGY_MODE = {
    "sft": "sft",
    "preference": "preference",
    "kto": "kto",
    "evaluation": "evaluation",
}

# per-topology requirements appended to the rendered generation prompt (WP D1):
# the model must know exactly what shape to return and how to behave refusal-wise.
_TOPOLOGY_REQ = {
    "sft": (
        "Return a conversation (messages) with a final assistant turn that answers "
        "the question strictly from the source material."
    ),
    "preference": (
        "Return prompt_messages plus chosen_messages and rejected_messages; the "
        "rejected answer must differ only in the way named by rejected_defect."
    ),
    "kto": (
        "Return messages plus desirability=good when the response is faithful to "
        "the source, bad otherwise."
    ),
    "evaluation": (
        "Return a self-contained question plus a reference_answer that exists in the "
        "source material."
    ),
}

# temperature scales a little with difficulty so harder samples vary more
_DIFFICULTY_TEMPERATURE = {"basic": 0.1, "intermediate": 0.3, "advanced": 0.5}

# static generation-scaffold slots; "question"/candidates are filled with
# directives because this is synthetic generation, not an interactive QA turn.
_SLOTS = {
    "question": (
        "(generate a single, self-contained question fully answerable from the source material)"
    ),
    "candidate_a": "(the more accurate, faithful candidate answer you generate)",
    "candidate_b": "(a subtly inferior candidate answer you generate)",
    "response": "(the answer you generate)",
}


@dataclass
class GenerationOutcome:
    batches: list[GeneratedBatch] = field(default_factory=list)
    manifest: PromptManifest = field(default_factory=PromptManifest)
    candidates_generated: int = 0
    calls_attempted: int = 0
    errors: list[str] = field(default_factory=list)

    def candidate_count_by_topology(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for b in self.batches:
            for c in b.candidates:
                topo = getattr(c, "topology", None) or _topology_of(c)
                counts[topo] = counts.get(topo, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates_generated": self.candidates_generated,
            "calls_attempted": self.calls_attempted,
            "by_topology": self.candidate_count_by_topology(),
            "manifest_hash": self.manifest.manifest_hash(),
            "errors": self.errors,
        }


def _topology_of(candidate: Any) -> str:
    if hasattr(candidate, "prompt_messages"):
        return "preference"
    if hasattr(candidate, "desirability"):
        return "kto"
    if hasattr(candidate, "question"):
        return "evaluation"
    return "sft"


class Generator:
    """Standalone generator over an already-built gateway."""

    def __init__(
        self,
        *,
        gateway: Any,
        max_chunks_per_spec: int = 200,
        max_repair_attempts: int = 1,
    ) -> None:
        self._gateway = gateway
        self._max_chunks_per_spec = max_chunks_per_spec
        self._max_repair_attempts = max_repair_attempts

    async def generate_for_plan(
        self,
        *,
        chunks: list[Any],
        plan: PlanResult,
        source_text_for: Any = None,
        span_ids_for: Any = None,
        seed_base: int = 1,
    ) -> GenerationOutcome:
        """Run every spec in the plan across available chunks (round-robin)."""
        from ..application.abuse import begin_generation_run

        begin_generation_run()
        src_text = source_text_for or (lambda c: getattr(c, "main_text", ""))
        spids = span_ids_for or (lambda c: getattr(c, "source_span_ids", []) or [])

        outcome = GenerationOutcome()
        for spec in plan.specs:
            if not chunks:
                break
            per_plan = spec.per_chunk
            # allocate across chunks round robin, capped per chunk
            remaining = per_plan
            idx = 0
            guard = 0
            while remaining > 0 and guard < len(chunks) * self._max_chunks_per_spec:
                chunk = chunks[idx % len(chunks)]
                idx += 1
                guard += 1
                text = src_text(chunk)
                if not text:
                    continue
                try:
                    batch, manifest_rec = await self._generate_one(
                        spec=spec,
                        chunk=chunk,
                        source_text=text,
                        source_span_ids=spids(chunk),
                        seed=seed_base * 1000 + idx,
                    )
                except ProviderError as exc:
                    from ..infrastructure.telemetry.metrics import get_registry

                    get_registry().inc(
                        "knovaryn_provider_errors_total",
                        labels={"topology": spec.topology, "task_family": spec.task_family},
                    )
                    outcome.errors.append(f"{spec.topology}/{spec.task_family}: {exc}")
                    continue
                outcome.batches.append(batch)
                if manifest_rec is not None:
                    outcome.manifest.add(manifest_rec)
                outcome.candidates_generated += len(batch.candidates)
                remaining -= len(batch.candidates)
        return outcome

    async def _generate_one(
        self,
        *,
        spec: AssignmentSpec,
        chunk: Any,
        source_text: str,
        source_span_ids: list[str],
        seed: int,
    ) -> tuple[GeneratedBatch, Any]:
        tpl = get_template(spec.task_family, spec.topology)
        schema_hash = schema_hash_for(spec.topology)
        sampling = {
            "temperature": _DIFFICULTY_TEMPERATURE.get(spec.difficulty, 0.3),
            "max_output_tokens": 1200,
        }
        messages = self._render_messages(spec, tpl, source_text)
        call_kwargs = {
            "prompt_template_version": tpl.version,
            "sampling": sampling,
            "schema_hash": schema_hash,
            "source_hashes": [getattr(chunk, "sha256", "") or ""],
            "messages": messages,
            "mode": _TOPOLOGY_MODE[spec.topology],
            "source_text": source_text,
            "chunk_id": getattr(chunk, "id", ""),
            "source_span_ids": source_span_ids,
            "task_family": spec.task_family,
            "difficulty": spec.difficulty,
            "model": None,
        }

        # D3 bounded repair: validate every provider response against the local
        # schema; on failure re-request up to max_repair_attempts with an explicit
        # correction, then quarantine (raise) rather than silently default-fill.
        for attempt in range(self._max_repair_attempts + 1):
            call_kwargs["seed"] = seed + attempt
            # J7: a configured per-run provider-call cap (abuse control).
            from ..application.abuse import enforce_provider_call

            enforce_provider_call()
            outcome = await self._gateway.generate(**call_kwargs)
            body = outcome.get("content") or {}
            codes = validate_generation_output(spec.topology, body)
            if not codes:
                batch = self._candidate_from_body(
                    body,
                    spec,
                    chunk_id=getattr(chunk, "id", ""),
                    source_document_id=getattr(chunk, "source_document_id", ""),
                    source_group_id=getattr(chunk, "source_group_id", None),
                    split=getattr(chunk, "split", ""),
                )
                rec = build_prompt_usage_record(
                    candidate_id=chunk.id + f"::{spec.topology}::{seed}",
                    chunk_id=chunk.id,
                    task_family=spec.task_family,
                    topology=spec.topology,
                    template_name=tpl.name,
                    template_version=tpl.version,
                    slots={"source_text": source_text},
                    messages=messages,
                    model=self._gateway.generator_model,
                )
                return batch, rec
            if attempt < self._max_repair_attempts:
                messages = messages + [
                    {
                        "role": "assistant",
                        "content": "(repairing) output did not match the required schema.",
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Your previous output failed local validation: {codes}. "
                            "Return a single JSON object conforming exactly to the schema; "
                            "do not omit required fields and never invent evidence span ids."
                        ),
                    },
                ]
        raise ProviderError(
            f"output failed schema validation for {spec.topology} after "
            f"{self._max_repair_attempts} repairs: {codes}",
            retryable=False,
        )

    def _render_messages(
        self, spec: AssignmentSpec, tpl: TemplateRef, source_text: str
    ) -> list[dict[str, str]]:
        """Render the versioned template into (system, user) messages (WP D1).

        The system message carries the source-as-data boundary; the user message
        embeds the source material plus explicit topology/difficulty/evidence/
        answerability requirements and the exact structured-output schema. Never
        sends raw source text alone.
        """
        slots = dict(_SLOTS)
        slots["source_text"] = source_text
        system, user = render(tpl, slots=slots)
        user += (
            f"\n\nTASK_FAMILY: {spec.task_family}\n"
            f"DIFFICULTY: {spec.difficulty}\n"
            f"TOPOLOGY: {spec.topology}\n"
            f"Requirement: {_TOPOLOGY_REQ.get(spec.topology, '')}\n"
            "Cite supporting evidence spans when relevant. If the source material is "
            "insufficient, set answerability=unanswerable rather than guessing. "
            "Never fabricate evidence or span ids.\n"
            f"Return a single JSON object conforming exactly to this schema:\n"
            f"{encode_schema_for_wire(spec.topology)}"
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def _template_version(self, spec: AssignmentSpec) -> str:
        try:
            return get_template(spec.task_family, spec.topology).version
        except KeyError:
            return "1"

    def _candidate_from_body(
        self,
        body: dict[str, Any],
        spec: AssignmentSpec,
        chunk_id: str,
        source_document_id: str,
        source_group_id: str | None,
        split: str,
    ) -> GeneratedBatch:
        topo = spec.topology
        # typed Any: source_group_id is legitimately None, but split/source_document_id
        # are str; a literal keeps the spread mypy-valid without runtime change.
        lineage: dict[str, Any] = {
            "chunk_id": chunk_id,
            "source_document_id": source_document_id,
            "source_group_id": source_group_id,
            "split": split,
        }
        cand: (
            GeneratedSFTCandidate
            | GeneratedPreferenceCandidate
            | GeneratedKTOCandidate
            | GeneratedEvaluationCandidate
            | None
        ) = None
        if topo == "sft":
            cand = GeneratedSFTCandidate(
                task_family=spec.task_family,
                difficulty=cast(Literal["basic", "intermediate", "advanced"], spec.difficulty),
                messages=_coerce_messages(body.get("messages")),
                evidence=_coerce_evidence(body.get("evidence")),
                answerability=body.get("answerability", "answerable"),
                concise_generation_note=body.get("concise_generation_note", ""),
                **lineage,
            )
        else:
            # preference / kto / evaluation: cast from canonical body
            try:
                cand = _generic_candidate(body, spec, **lineage)
            except Exception as exc:  # noqa: BLE001
                raise ProviderError(
                    f"candidate parse failed for {topo}: {exc}", retryable=False
                ) from exc
        return GeneratedBatch(
            candidates=[cand], generation_note=body.get("concise_generation_note", "")
        )


def _coerce_messages(raw: Any) -> list[CanonicalMessage]:
    if not isinstance(raw, list):
        return [CanonicalMessage(role="user", content="")]
    out: list[CanonicalMessage] = []
    for m in raw:
        out.append(
            CanonicalMessage(
                role=m.get("role", "user"),
                content=m.get("content", ""),
                name=m.get("name"),
                tool_call_id=m.get("tool_call_id"),
            )
        )
    return out


def _coerce_evidence(raw: Any) -> list[EvidenceRef]:
    if not isinstance(raw, list):
        return []
    out: list[EvidenceRef] = []
    for e in raw:
        if isinstance(e, dict):
            out.append(
                EvidenceRef(
                    span_id=e.get("span_id", ""),
                    support_type=e.get("support_type", SupportType.direct),
                )
            )
    return out


def _generic_candidate(
    body: dict[str, Any],
    spec: AssignmentSpec,
    chunk_id: str = "",
    source_document_id: str = "",
    source_group_id: str | None = None,
    split: str = "",
) -> GeneratedPreferenceCandidate | GeneratedKTOCandidate | GeneratedEvaluationCandidate:
    """Build the topology-specific candidate from the canonical fake-provider body."""
    topo = spec.topology
    lineage: dict[str, Any] = {
        "chunk_id": chunk_id,
        "source_document_id": source_document_id,
        "source_group_id": source_group_id,
        "split": split,
    }
    if topo == "preference":
        return GeneratedPreferenceCandidate(
            task_family=spec.task_family,
            prompt_messages=_coerce_messages(body.get("prompt_messages") or body.get("messages")),
            chosen_messages=_coerce_messages(body.get("chosen_messages")),
            rejected_messages=_coerce_messages(body.get("rejected_messages")),
            evidence=_coerce_evidence(body.get("evidence")),
            rejected_defect=body.get("rejected_defect", "subtle_factual_error"),
            expected_preference_margin=body.get("expected_preference_margin", "medium"),
            concise_generation_note=body.get("concise_generation_note", ""),
            **lineage,
        )
    if topo == "kto":
        return GeneratedKTOCandidate(
            task_family=spec.task_family,
            messages=_coerce_messages(body.get("messages")),
            desirability=body.get("desirability", "good"),
            evidence=_coerce_evidence(body.get("evidence")),
            concise_generation_note=body.get("concise_generation_note", ""),
            **lineage,
        )
    if topo == "evaluation":
        return GeneratedEvaluationCandidate(
            task_family=spec.task_family,
            question=body.get("question", ""),
            reference_answer=body.get("reference_answer"),
            evidence=_coerce_evidence(body.get("evidence")),
            concise_generation_note=body.get("concise_generation_note", ""),
            **lineage,
        )
    raise ProviderError(f"unknown topology {topo}", retryable=False)
