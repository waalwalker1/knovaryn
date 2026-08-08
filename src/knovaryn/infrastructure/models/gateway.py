"""Model gateway (spec §11).

Normalized completion over fake and real (OpenAI-compatible / Anthropic-enabled)
providers. Wires fingerprint caching (resume-safe), capability negotiation,
structured output, budget checks, and cost-ledger recording. Domain never
imports provider clients.
"""

from __future__ import annotations

import time
from typing import Any

from ...domain.errors import BudgetExceededError, ProviderError, UnsupportedOperationError
from ...domain.hashing import fingerprint as make_fingerprint
from ...domain.schemas import utcnow
from .call_cache import CallCache
from .capabilities import Capability, CapabilityCache, ProviderCapabilities
from .cost import PriceProfile, build_cost_entry, estimate_call_cost
from .fake_provider import FakeProvider


class ModelGateway:
    def __init__(
        self,
        *,
        generator_model: str = "fake",
        critic_model: str = "fake",
        verifier_model: str = "fake",
        temperature: float = 0.3,
        max_output_tokens: int = 2400,
        price_profile: PriceProfile | None = None,
        call_cache: CallCache | None = None,
        capability_cache: CapabilityCache | None = None,
        fake: FakeProvider | None = None,
        real_provider: Any = None,
        budget: Any = None,
        cost_repo: Any = None,
        project_id: str | None = None,
        job_id: str | None = None,
        stage: str = "",
    ) -> None:
        self.generator_model = generator_model
        self.critic_model = critic_model
        self.verifier_model = verifier_model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.price_profile = price_profile
        self._cache = call_cache or CallCache(store=_NullStore())
        self._caps = capability_cache or CapabilityCache()
        self._fake = fake or FakeProvider(temperature=temperature, max_output_tokens=max_output_tokens)
        self._real = real_provider
        self._budget = budget
        self._cost_repo = cost_repo
        self._project_id = project_id
        self._job_id = job_id
        self._stage = stage

    # -- provider resolution -------------------------------------------------
    def _is_fake(self, model: str) -> bool:
        return model in ("fake", "") or self._real is None or model == "fake"

    def supports(self, cap: Capability, model: str = "fake") -> bool:
        if model in ("fake", "") or self._real is None:
            return self._fake.capabilities.supports(cap)
        key_caps = self._caps.get("configured", model)
        if key_caps is None:
            return False
        return key_caps.supports(cap)

    # -- completion ----------------------------------------------------------
    async def generate(
        self,
        *,
        prompt_template_version: str | None,
        sampling: dict[str, Any],
        schema_hash: str | None,
        source_hashes: list[str],
        messages: list[dict[str, Any]],
        mode: str = "sft",
        source_text: str = "",
        chunk_id: str = "",
        source_span_ids: list[str] | None = None,
        task_family: str = "factual_explanation",
        difficulty: str = "intermediate",
        model: str | None = None,
        seed: int | None = None,
    ) -> dict[str, Any]:
        model = model or self.generator_model
        if self._budget is not None:
            self._budget.check()

        fp = make_fingerprint(
            messages=messages,
            prompt_template_version=prompt_template_version,
            model=model,
            sampling=sampling,
            schema_hash=schema_hash,
            source_hashes=source_hashes,
        )
        cached = await self._cache.get(fp)
        if cached is not None:
            return cached

        start = time.monotonic()
        if self._is_fake(model):
            result = await self._fake.complete(
                messages=messages,
                temperature=sampling.get("temperature", self.temperature),
                max_output_tokens=sampling.get("max_output_tokens", self.max_output_tokens),
                source_text=source_text,
                chunk_id=chunk_id,
                source_span_ids=source_span_ids,
                task_family=task_family,
                difficulty=difficulty,
                mode=mode,
                seed=seed,
            )
        elif self._real is not None:
            result = await self._real.complete(
                model=model,
                messages=messages,
                temperature=sampling.get("temperature", 0.0),
                max_output_tokens=sampling.get("max_output_tokens", self.max_output_tokens),
                schema_hash=schema_hash,
            )
        else:
            raise UnsupportedOperationError("no live provider configured and model is not 'fake'")

        latency = int((time.monotonic() - start) * 1000)
        result["_fingerprint"] = fp
        result["_latency_ms"] = latency

        # cost accounting
        entry = build_cost_entry(
            provider="fake" if self._is_fake(model) else "configured",
            model=model,
            usage=result.get("usage"),
            profile=self.price_profile,
            latency_ms=latency,
            provider_request_id=(result.get("usage") or {}).get("provider_request_id"),
        )
        if self._budget is not None:
            self._budget.account_call(
                cost_usd=entry["estimated_cost"],
                input_tokens=entry["input_tokens"],
                output_tokens=entry["output_tokens"],
            )
        if self._cost_repo is not None:
            try:
                await self._cost_repo.record(
                    {
                        **entry,
                        "job_id": self._job_id,
                        "project_id": self._project_id,
                        "stage": self._stage,
                    }
                )
            except Exception:
                pass  # cost recording must never block generation

        await self._cache.put(fp, result)
        return result

    def estimated_cost_accumulated(self) -> float:
        return self._budget.spent_cost_usd if self._budget is not None else 0.0


class _NullStore:
    """Best-effort placeholder store that never holds data (tests without CAS)."""

    async def put(self, *a, **k) -> dict:  # noqa: ANN001, ANN002, ANN003
        return {}

    async def get(self, *a) -> bytes:  # noqa: ANN001, ANN002
        from ...domain.errors import NotFoundError

        raise NotFoundError("null store")


def estimate_generation_cost(
    *,
    tokens_in: int,
    tokens_out: int,
    profile: PriceProfile,
    calls: int,
) -> float:
    return round(estimate_call_cost(profile, input_tokens=tokens_in, output_tokens=tokens_out) * calls, 6)
