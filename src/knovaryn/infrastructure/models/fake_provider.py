"""Deterministic fake model provider (spec §11.2, exec rule 2).

Default for CI, examples, and the offline demo. No credentials. Produces
structured, deterministic candidates from the supplied evidence so the full
pipeline (generation → validation → quality → version → export) runs end to end.
"""

from __future__ import annotations

import random
import re
from typing import Any, Literal, cast

from ...domain import schemas
from ...domain.errors import ProviderError
from ...domain.policies import approximate_tokens
from .capabilities import (
    capability_set,
)

_FACT_SENTENCES = re.compile(r"(?<=[.!?])\s+")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$", re.MULTILINE)


def _sentences(text: str) -> list[str]:
    parts = _FACT_SENTENCES.split(text)
    return [s.strip() for s in parts if len(s.strip()) >= 12]


def _make_span_id(chunk_id: str, i: int) -> str:
    return f"span_{chunk_id[-8:]}_{i}"


class FakeProvider:
    """Deterministic generator/critic. All results derive from input evidence."""

    name = "fake"
    capabilities = capability_set(
        structured_output=True,
        tool_use=False,
        image_input=False,
        seed=True,
        batch=False,
        usage_reporting=True,
    )

    def __init__(self, *, temperature: float = 0.3, max_output_tokens: int = 1200) -> None:
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens

    async def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        schema: Any = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        source_text: str = "",
        chunk_id: str = "",
        source_span_ids: list[str] | None = None,
        task_family: str = "factual_explanation",
        difficulty: str = "intermediate",
        mode: str = "sft",
        seed: int | None = None,
        usage: bool = True,
    ) -> dict[str, Any]:
        """Return a canonical candidate + fake usage, fully deterministic."""
        sentences = _sentences(source_text)
        if not sentences:
            raise ProviderError("no evidence sentences available", retryable=False)
        span_ids = source_span_ids or [
            _make_span_id(chunk_id, i) for i in range(min(len(sentences), 6))
        ]

        # deterministic pseudo-random selection from the seed so output is stable
        rng_seed = seed if seed is not None else (_hash(chunk_id) % 100000)
        rng = random.Random(rng_seed)

        cand: (
            schemas.GeneratedSFTCandidate
            | schemas.GeneratedPreferenceCandidate
            | schemas.GeneratedKTOCandidate
            | schemas.GeneratedEvaluationCandidate
        )
        if mode == "preference":
            cand = self._preference(sentences, span_ids, task_family, difficulty, rng)
        elif mode == "kto":
            cand = self._kto(sentences, span_ids, task_family, difficulty, rng)
        elif mode == "evaluation":
            cand = self._evaluation(sentences, span_ids, task_family, difficulty, rng)
        else:
            cand = self._sft(sentences, span_ids, task_family, difficulty, rng)

        body = cand.model_dump(mode="json")
        total_input = sum(approximate_tokens(m["content"]) for m in messages) + 64
        output_tokens = approximate_tokens(body.get("concise_generation_note", "")) + len(str(body))
        usage_info = {
            "input_tokens": total_input,
            "output_tokens": output_tokens,
            "total_tokens": total_input + output_tokens,
            "provider_request_id": f"fake_{chunk_id[:8]}_{seed}",
        }
        return {"content": body, "usage": usage_info, "model": "fake"}

    # -- generators ---------------------------------------------------------
    def _sft(
        self,
        sentences: list[str],
        span_ids: list[str],
        task_family: str,
        difficulty: str,
        rng: random.Random,
    ) -> schemas.GeneratedSFTCandidate:
        chosen_sentences = [sentences[i % len(sentences)] for i in range(2)]
        main = " ".join(chosen_sentences)
        answer = self._answer_from(main, task_family)
        user_q = _question_from(main, sentences[0], task_family, difficulty)
        messages = [
            schemas.CanonicalMessage(role="system", content="You are a careful domain assistant."),
            schemas.CanonicalMessage(role="user", content=user_q),
            schemas.CanonicalMessage(role="assistant", content=answer),
        ]
        evidence = [
            schemas.EvidenceRef(span_id=span_ids[0], support_type=schemas.SupportType.direct)
        ]
        return schemas.GeneratedSFTCandidate(
            task_family=task_family,
            difficulty=cast(Literal["basic", "intermediate", "advanced"], difficulty),
            messages=messages,
            evidence=evidence,
            answerability="answerable",
            concise_generation_note="fake-provider ground truth SFT",
        )

    def _preference(
        self,
        sentences: list[str],
        span_ids: list[str],
        task_family: str,
        difficulty: str,
        rng: random.Random,
    ) -> schemas.GeneratedPreferenceCandidate:
        chosen_sentences = [sentences[i % len(sentences)] for i in range(2)]
        main = " ".join(chosen_sentences)
        prompt = _question_from(main, sentences[0], task_family, difficulty)
        chosen = schemas.CanonicalMessage(
            role="assistant", content=self._answer_from(main, task_family)
        )
        # controlled near-miss: drop a fact clause
        rejected_text = _make_near_miss(main)
        rejected = schemas.CanonicalMessage(
            role="assistant", content=self._answer_from(rejected_text, task_family)
        )
        defect: Literal["subtle_factual_error"] = "subtle_factual_error"
        return schemas.GeneratedPreferenceCandidate(
            task_family=task_family,
            prompt_messages=[schemas.CanonicalMessage(role="user", content=prompt)],
            chosen_messages=[chosen],
            rejected_messages=[rejected],
            evidence=[
                schemas.EvidenceRef(span_id=span_ids[0], support_type=schemas.SupportType.direct)
            ],
            rejected_defect=defect,
            expected_preference_margin="medium",
            concise_generation_note="fake-provider near-miss preference",
        )

    def _kto(
        self,
        sentences: list[str],
        span_ids: list[str],
        task_family: str,
        difficulty: str,
        rng: random.Random,
    ) -> schemas.GeneratedKTOCandidate:
        main = " ".join(sentences[:2])
        q = _question_from(main, sentences[0], task_family, difficulty)
        return schemas.GeneratedKTOCandidate(
            task_family=task_family,
            messages=[
                schemas.CanonicalMessage(role="user", content=q),
                schemas.CanonicalMessage(
                    role="assistant", content=self._answer_from(main, task_family)
                ),
            ],
            desirability="good",
            evidence=[
                schemas.EvidenceRef(span_id=span_ids[0], support_type=schemas.SupportType.direct)
            ],
            concise_generation_note="fake-provider KTO good example",
        )

    def _evaluation(
        self,
        sentences: list[str],
        span_ids: list[str],
        task_family: str,
        difficulty: str,
        rng: random.Random,
    ) -> schemas.GeneratedEvaluationCandidate:
        main = " ".join(sentences[:1])
        q = _question_from(main, sentences[0], task_family, difficulty)
        return schemas.GeneratedEvaluationCandidate(
            task_family=task_family,
            question=q,
            reference_answer=self._answer_from(main, task_family),
            evidence=[
                schemas.EvidenceRef(span_id=span_ids[0], support_type=schemas.SupportType.direct)
            ],
            concise_generation_note="fake-provider evaluation item",
        )

    def _answer_from(self, main: str, task_family: str) -> str:
        if task_family == "procedure":
            return f"To handle this, follow the steps described: {main}"
        if task_family == "troubleshooting":
            return f"Based on the material: {main}"
        if task_family == "comparison":
            return f"A fair comparison based on the evidence: {main}"
        return f"According to the provided material: {main}"


def _question_from(main: str, first: str, task_family: str, difficulty: str) -> str:
    if task_family == "procedure":
        return "What are the key steps to accomplish this task?"
    if task_family == "troubleshooting":
        return "How should one resolve the issue described in the material?"
    if task_family == "comparison":
        return "How do the described options compare according to the material?"
    if difficulty == "advanced":
        return (
            "Explain the underlying reasons and implications of the following, "
            "based only on the material: " + first[:180]
        )
    return "Based only on the provided material, summarize the key point about: " + first[:180]


def _make_near_miss(text: str) -> str:
    """Produce a controlled near-miss by dropping a substantive clause."""
    clauses = re.split(r"(?<=\.)\s+", text)
    if len(clauses) > 1:
        return " ".join(clauses[:-1]) + " (the remaining detail was not confirmed in the material)."
    return text + " (this additional claim was not supported)."


def _hash(text: str) -> int:
    import hashlib

    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
