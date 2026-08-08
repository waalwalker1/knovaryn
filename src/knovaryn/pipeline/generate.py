"""Generation stage (spec §12.5/§12.6).

Turns source chunks into generated candidates (SFT / preference / KTO /
evaluation) by invoking the model gateway with versioned prompt templates and
recording a prompt manifest for auditability. Deterministic under the fake
provider; cancel-safe and idempotent via the incoming ``StageContext``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.errors import ProviderError
from ..domain.schemas import GeneratedBatch, GeneratedSFTCandidate
from ..domain.schemas import utcnow
from ..prompts.library import get_template, render
from ..prompts.manifest import PromptManifest, build_prompt_usage_record
from .planner import AssignmentSpec, PlanResult

_TOPOLOGY_MODE = {
    "sft": "sft",
    "preference": "preference",
    "kto": "kto",
    "evaluation": "evaluation",
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


def _topology_of(candidate) -> str:  # noqa: ANN001
    if hasattr(candidate, "prompt_messages"):
        return "preference"
    if hasattr(candidate, "desirability"):
        return "kto"
    if hasattr(candidate, "question"):
        return "evaluation"
    return "sft"


class Generator:
    """Standalone generator over an already-built gateway."""

    def __init__(self, *, gateway: Any, max_chunks_per_spec: int = 200) -> None:
        self._gateway = gateway
        self._max_chunks_per_spec = max_chunks_per_spec

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
        src_text = source_text_for or (lambda c: getattr(c, "main_text", ""))
        spids = span_ids_for or (lambda c: getattr(c, "source_span_ids", []) or [])

        outcome = GenerationOutcome()
        for spec in plan.specs:
            if not chunks:
                break
            per_plan = spec.per_chunk
            # allocate across chunks round robin, capped per chunk
            per_chunk = max(1, per_plan // len(chunks)) if per_plan else 1
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
                    outcome.errors.append(f"{spec.topology}/{spec.task_family}: {exc}")
                    continue
                outcome.batches.append(batch)
                if manifest_rec is not None:
                    outcome.manifest.add(manifest_rec)
                outcome.candidates_generated += len(batch.candidates)
                remaining -= len(batch.candidates)
        return outcome

    async def _generate_one(self, *, spec: AssignmentSpec, chunk, source_text: str, source_span_ids: list[str], seed: int) -> tuple[GeneratedBatch, Any]:
        outcome = await self._gateway.generate(
            prompt_template_version=self._template_version(spec),
            sampling={"temperature": 0.3, "max_output_tokens": 1200},
            schema_hash="knovaryn-candidate/v1",
            source_hashes=[getattr(chunk, "sha256", "") or ""],
            messages=[{"role": "user", "content": source_text}],
            mode=_TOPOLOGY_MODE[spec.topology],
            source_text=source_text,
            chunk_id=getattr(chunk, "id", ""),
            source_span_ids=source_span_ids,
            task_family=spec.task_family,
            difficulty=spec.difficulty,
            seed=seed,
            model=None,
        )
        body = outcome.get("content") or {}
        batch = self._candidate_from_body(body, spec, chunk.id)
        rec = build_prompt_usage_record(
            candidate_id=chunk.id + f"::{spec.topology}::{seed}",
            chunk_id=chunk.id,
            task_family=spec.task_family,
            topology=spec.topology,
            template_name=spec.topology,
            template_version=self._template_version(spec),
            slots={"source_text": source_text},
            messages=[{"role": "user", "content": source_text}],
            model=self._gateway.generator_model,
        )
        return batch, rec

    def _template_version(self, spec: AssignmentSpec) -> str:
        try:
            return get_template(spec.task_family, spec.topology).version
        except KeyError:
            return "1"

    def _candidate_from_body(self, body: dict[str, Any], spec: AssignmentSpec, chunk_id: str) -> GeneratedBatch:
        import json

        topo = spec.topology
        cand = None
        if topo == "sft":
            cand = GeneratedSFTCandidate(
                task_family=spec.task_family,
                difficulty=spec.difficulty,
                messages=_coerce_messages(body.get("messages")),
                evidence=_coerce_evidence(body.get("evidence")),
                answerability=body.get("answerability", "answerable"),
                concise_generation_note=body.get("concise_generation_note", ""),
            )
        else:
            # preference / kto / evaluation: cast from canonical body
            try:
                cand = _generic_candidate(body, spec)
            except Exception as exc:  # noqa: BLE001
                raise ProviderError(f"candidate parse failed for {topo}: {exc}", retryable=False) from exc
        return GeneratedBatch(candidates=[cand], generation_note=body.get("concise_generation_note", ""))


def _coerce_messages(raw) -> list:  # noqa: ANN001
    from ..domain.schemas import CanonicalMessage

    if not isinstance(raw, list):
        return [CanonicalMessage(role="user", content="")]
    out = []
    for m in raw:
        out.append(CanonicalMessage(
            role=m.get("role", "user"),
            content=m.get("content", ""),
            name=m.get("name"),
            tool_call_id=m.get("tool_call_id"),
        ))
    return out


def _coerce_evidence(raw) -> list:  # noqa: ANN001
    from ..domain.schemas import EvidenceRef, SupportType

    if not isinstance(raw, list):
        return []
    out = []
    for e in raw:
        if isinstance(e, dict):
            out.append(EvidenceRef(span_id=e.get("span_id", ""), support_type=e.get("support_type", SupportType.direct)))
    return out


def _generic_candidate(body: dict[str, Any], spec: AssignmentSpec):  # noqa: ANN001
    """Build the topology-specific candidate from the canonical fake-provider body."""
    from ..domain.schemas import (
        CanonicalMessage,
        GeneratedEvaluationCandidate,
        GeneratedKTOCandidate,
        GeneratedPreferenceCandidate,
    )

    topo = spec.topology
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
        )
    if topo == "kto":
        return GeneratedKTOCandidate(
            task_family=spec.task_family,
            messages=_coerce_messages(body.get("messages")),
            desirability=body.get("desirability", "good"),
            evidence=_coerce_evidence(body.get("evidence")),
            concise_generation_note=body.get("concise_generation_note", ""),
        )
    if topo == "evaluation":
        return GeneratedEvaluationCandidate(
            task_family=spec.task_family,
            question=body.get("question", ""),
            reference_answer=body.get("reference_answer"),
            evidence=_coerce_evidence(body.get("evidence")),
            concise_generation_note=body.get("concise_generation_note", ""),
        )
    raise ProviderError(f"unknown topology {topo}", retryable=False)
