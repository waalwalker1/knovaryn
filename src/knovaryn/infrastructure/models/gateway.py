"""Model gateway (spec §11).

Normalized completion over fake and real (OpenAI-compatible / Anthropic-enabled)
providers. Wires fingerprint caching (resume-safe), capability negotiation,
structured output, budget checks, and cost-ledger recording. Domain never
imports provider clients.
"""

from __future__ import annotations

import time
from contextlib import suppress
from typing import Any, cast

from ...domain.errors import UnsupportedOperationError
from ...domain.hashing import fingerprint as make_fingerprint
from .call_cache import CallCache
from .capabilities import Capability, CapabilityCache
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
        model_call_repo: Any = None,
        profile: str = "fake",
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
        self._fake = fake or FakeProvider(
            temperature=temperature, max_output_tokens=max_output_tokens
        )
        self._real = real_provider
        self._budget = budget
        self._cost_repo = cost_repo
        self._model_call_repo = model_call_repo
        self._profile = profile
        self._project_id = project_id
        self._job_id = job_id
        self._stage = stage

    @property
    def profile(self) -> str:
        """The runtime profile this gateway was wired for (defect 4.9)."""
        return self._profile

    # -- provider resolution -------------------------------------------------
    def _is_fake(self, model: str) -> bool:
        return model in ("fake", "") or model == "fake"

    def _resolve(self, model: str | None) -> tuple[str, str, str]:
        """Resolve a requested model to (span, requested_model, resolved_model).

        We never interpret ``real_provider is None`` as permission to silently
        generate with the fake provider (spec §11.5 / WP D5). A request for a
        real model with no live provider configured is an explicit failure, and
        only an explicit ``fake`` request may use fake generation.
        """
        requested = model or self.generator_model
        if requested in ("fake", ""):
            return ("fake", "fake", "fake")
        if self._real is None:
            raise UnsupportedOperationError(
                f"model '{requested}' requested but no live provider is configured; "
                "refusing to silently fall back to fake generation. Configure a "
                "provider or request model='fake' explicitly."
            )
        return ("live", requested, requested)

    def supports(self, cap: Capability, model: str = "fake") -> bool:
        if model in ("fake", "") or self._real is None:
            return self._fake.capabilities.supports(cap)
        key_caps = self._caps.get(getattr(self._real, "name", "configured"), model)
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
        # D5: resolve the model up front so a real-model request without a live
        # provider fails loudly instead of silently using fake generation.
        span, requested_model, resolved_model = self._resolve(model)
        fingerprint_model = requested_model if requested_model != "fake" else resolved_model
        if self._budget is not None:
            self._budget.check(model=resolved_model, stage=self._stage)

        fp = make_fingerprint(
            messages=messages,
            prompt_template_version=prompt_template_version,
            model=fingerprint_model,
            sampling=sampling,
            schema_hash=schema_hash,
            source_hashes=source_hashes,
        )
        cached = await self._cache.get(fp)
        if cached is not None:
            return cast(dict[str, Any], cached)

        # Durable dedup (spec §11.5): the in-memory cache is cold after a
        # crash, but the model_calls ledger recorded the paid call and its
        # result. Serve the fingerprint from the ledger instead of re-invoking
        # the provider — a resumed job never pays twice for the same call.
        if self._model_call_repo is not None and self._job_id:
            with suppress(Exception):
                prior = await self._model_call_repo.get_by_fingerprint(self._job_id, fp)
                if prior is not None and prior.status == "ok" and prior.result_payload:
                    restored = dict(prior.result_payload)
                    restored.setdefault("_fingerprint", fp)
                    await self._cache.put(fp, restored)
                    return cast(dict[str, Any], restored)

        start = time.monotonic()
        if span == "fake":
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
        else:
            result = await self._real.complete(
                model=resolved_model,
                messages=messages,
                temperature=sampling.get("temperature", 0.0),
                max_output_tokens=sampling.get("max_output_tokens", self.max_output_tokens),
                schema_hash=schema_hash,
            )

        latency = int((time.monotonic() - start) * 1000)
        result["_fingerprint"] = fp
        result["_latency_ms"] = latency

        # cost accounting
        provider_label = "fake" if span == "fake" else getattr(self._real, "name", "configured")
        usage = result.get("usage") or {}
        entry = build_cost_entry(
            provider=provider_label,
            model=resolved_model,
            usage=usage,
            profile=self.price_profile,
            latency_ms=latency,
            provider_request_id=usage.get("provider_request_id"),
        )
        if self._budget is not None:
            self._budget.account_call(
                cost_usd=entry["estimated_cost"],
                input_tokens=entry["input_tokens"],
                output_tokens=entry["output_tokens"],
                model=resolved_model,
                stage=self._stage,
            )
            # WP D7 — post-usage reconciliation: pause as soon as a call crosses
            # a hard limit, not on some later pre-call check.
            self._budget.reconcile(model=resolved_model, stage=self._stage)
        if self._cost_repo is not None:
            # cost recording must never block generation
            with suppress(Exception):
                await self._cost_repo.record(
                    {
                        **entry,
                        "job_id": self._job_id,
                        "project_id": self._project_id,
                        "stage": self._stage,
                    }
                )

        # D6: persist a full model-call ledger entry (audit trail). Never blocks.
        if self._model_call_repo is not None:
            with suppress(Exception):
                await self._model_call_repo.record(
                    {
                        "job_id": self._job_id,
                        "project_id": self._project_id,
                        "stage": self._stage,
                        "provider": provider_label,
                        "requested_model": requested_model,
                        "resolved_model": resolved_model,
                        "profile": self._profile,
                        "prompt_template_hash": prompt_template_version or "",
                        "request_fingerprint": fp,
                        "schema_hash": schema_hash or "",
                        "sampling_params": sampling,
                        "input_tokens": entry["input_tokens"],
                        "cached_input_tokens": entry.get("cached_input_tokens", 0),
                        "output_tokens": entry["output_tokens"],
                        "estimated_cost": entry["estimated_cost"],
                        "provider_request_id": usage.get("provider_request_id"),
                        "latency_ms": latency,
                        "retry_count": 0,
                        "result_artifact_id": None,
                        # the response payload makes the ledger the durable
                        # resume source: a cold-cache restart is served from
                        # this row instead of re-paying the call
                        "result_payload": result,
                        "status": "ok",
                    }
                )

        await self._cache.put(fp, result)
        return result

    def estimated_cost_accumulated(self) -> float:
        return self._budget.spent_cost_usd if self._budget is not None else 0.0

    # -- judge (defects 3.8/3.9) ---------------------------------------------
    async def judge(
        self,
        *,
        system: str,
        user: str,
        prompt_template_version: str,
        schema_hash: str,
        stage: str = "judge",
        max_output_tokens: int | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Cited-evidence-only judge call (defects 3.8/3.9).

        Verifier/judge completions share the exact plumbing of generation —
        fingerprinting, durable cache, budget accounting, and the model-call
        ledger — but differ in three ways: temperature is pinned to 0.0, the
        fake provider is NEVER used (a fake judge would fabricate "verified"
        verdicts), and a missing live provider raises instead of degrading.
        Returns the provider result dict with ``_fingerprint``/``_latency_ms``.
        """
        requested_model = model or self.verifier_model
        if requested_model in ("fake", ""):
            raise UnsupportedOperationError(
                "judge calls refuse the fake provider: a fabricated verdict can "
                "never certify quality. Configure a live verifier model."
            )
        if self._real is None:
            raise UnsupportedOperationError(
                f"judge model '{requested_model}' requested but no live provider "
                "is configured; refusing to fabricate judge verdicts."
            )
        resolved = requested_model
        if self._budget is not None:
            self._budget.check(model=resolved, stage=stage)

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        sampling = {
            "temperature": 0.0,
            "max_output_tokens": max_output_tokens or 1024,
        }
        fp = make_fingerprint(
            messages=messages,
            prompt_template_version=prompt_template_version,
            model=resolved,
            sampling=sampling,
            schema_hash=schema_hash,
            source_hashes=[],
        )
        cached = await self._cache.get(fp)
        if cached is not None:
            return cast(dict[str, Any], cached)

        start = time.monotonic()
        result = await self._real.complete(
            model=resolved,
            messages=messages,
            temperature=0.0,
            max_output_tokens=sampling["max_output_tokens"],
            schema_hash=schema_hash,
        )
        latency = int((time.monotonic() - start) * 1000)
        result["_fingerprint"] = fp
        result["_latency_ms"] = latency

        provider_label = getattr(self._real, "name", "configured")
        usage = result.get("usage") or {}
        entry = build_cost_entry(
            provider=provider_label,
            model=resolved,
            usage=usage,
            profile=self.price_profile,
            latency_ms=latency,
            provider_request_id=usage.get("provider_request_id"),
        )
        if self._budget is not None:
            self._budget.account_call(
                cost_usd=entry["estimated_cost"],
                input_tokens=entry["input_tokens"],
                output_tokens=entry["output_tokens"],
                model=resolved,
                stage=stage,
            )
            self._budget.reconcile(model=resolved, stage=stage)
        if self._cost_repo is not None:
            with suppress(Exception):
                await self._cost_repo.record(
                    {
                        **entry,
                        "job_id": self._job_id,
                        "project_id": self._project_id,
                        "stage": stage,
                    }
                )
        if self._model_call_repo is not None:
            with suppress(Exception):
                await self._model_call_repo.record(
                    {
                        "job_id": self._job_id,
                        "project_id": self._project_id,
                        "stage": stage,
                        "provider": provider_label,
                        "requested_model": requested_model,
                        "resolved_model": resolved,
                        "profile": self._profile,
                        "prompt_template_hash": prompt_template_version,
                        "request_fingerprint": fp,
                        "schema_hash": schema_hash,
                        "sampling_params": sampling,
                        "input_tokens": entry["input_tokens"],
                        "cached_input_tokens": entry.get("cached_input_tokens", 0),
                        "output_tokens": entry["output_tokens"],
                        "estimated_cost": entry["estimated_cost"],
                        "provider_request_id": usage.get("provider_request_id"),
                        "latency_ms": latency,
                        "retry_count": 0,
                        "result_artifact_id": None,
                        "result_payload": result,
                        "status": "ok",
                    }
                )
        await self._cache.put(fp, result)
        return result


class _NullStore:
    """Best-effort placeholder store that never holds data (tests without CAS)."""

    async def put(self, *a: Any, **k: Any) -> dict:
        return {}

    async def get(self, *a: Any) -> bytes:
        from ...domain.errors import NotFoundError

        raise NotFoundError("null store")


def estimate_generation_cost(
    *,
    tokens_in: int,
    tokens_out: int,
    profile: PriceProfile,
    calls: int,
) -> float:
    return round(
        estimate_call_cost(profile, input_tokens=tokens_in, output_tokens=tokens_out) * calls, 6
    )
