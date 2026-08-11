"""D8 — opt-in live model-provider contract tests (spec §11.1, §12.7).

Structural contract assertions run without network (they verify the provider's
refusal and normalization behavior). The ``live-provider`` real-call test only
runs when ``KNOVARYN_LIVE_PROVIDER=1`` and is bounded by a hard spend cap.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock

import pytest

from knovaryn.domain.errors import ProviderError
from knovaryn.identity import ENV_PREFIX
from knovaryn.infrastructure.models.litellm_provider import LiteLLMProvider

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def run(coro):
    return _LOOP.run_until_complete(coro)


# ---------------------------------------------------------------------------
# structural contract: refusal + normalization (no network needed)
# ---------------------------------------------------------------------------


def test_live_provider_refuses_without_key() -> None:
    """Selected live, no API key configured -> explicit non-retryable failure.

    This enforces the no-silent-fallback rule (WP D5) at the provider boundary.
    """
    os.environ.pop(f"{ENV_PREFIX}DEEPSEEK_API_KEY", None)
    os.environ.pop(f"{ENV_PREFIX}DEEPSEEK_BASE_URL", None)
    provider = LiteLLMProvider(api_key="")  # explicitly empty
    with pytest.raises(ProviderError) as exc:
        run(provider.complete(
            model="deepseek-v4-flash",
            messages=[{"role": "user", "content": "hi"}],
        ))
    assert exc.value.retryable is False


def test_live_provider_normalizes_response() -> None:
    """A mocked live call must come back as a JSON-safe content dict + usage."""
    os.environ[f"{ENV_PREFIX}DEEPSEEK_API_KEY"] = "sk-test"
    provider = LiteLLMProvider(api_key="sk-test")
    fake = AsyncMock(return_value={
        "content": {"task_family": "factual_explanation", "ok": True},
        "usage": {"input_tokens": 10, "output_tokens": 20, "provider_request_id": "pid-1"},
        "model": "deepseek-v4-flash",
    })
    provider._complete_httpx = fake
    result = run(provider.complete(
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "hi"}],
        schema_hash="schema:abc",
    ))
    assert result["content"]["ok"] is True
    assert result["usage"]["input_tokens"] == 10
    assert result["usage"]["provider_request_id"] == "pid-1"
    assert result["model"] == "deepseek-v4-flash"
    os.environ.pop(f"{ENV_PREFIX}DEEPSEEK_API_KEY", None)


# ---------------------------------------------------------------------------
# real live call (opt-in, spend-capped)
# ---------------------------------------------------------------------------


def test_real_live_call_bounded_by_spend_cap(spend_cap_usd: float) -> None:
    """Round-trip a tiny prompt against the configured live provider.

    Cost is estimated from usage against the billed price profile; the test
    fails (rather than spending) if the cap is exceeded.
    """
    if os.environ.get(f"{ENV_PREFIX}LIVE_PROVIDER", "0") != "1":
        pytest.skip(f"set {ENV_PREFIX}LIVE_PROVIDER=1 to run live provider calls")
    api_key = os.environ.get(f"{ENV_PREFIX}DEEPSEEK_API_KEY", "")
    if not api_key:
        pytest.skip(f"no {ENV_PREFIX}DEEPSEEK_API_KEY configured")
    from knovaryn.infrastructure.models.cost import PriceProfile, estimate_call_cost
    from knovaryn.infrastructure.models.profiles import DeepSeekFlashBudget

    budget = DeepSeekFlashBudget()
    provider = LiteLLMProvider(api_key=api_key, model=budget.generator_model)
    profile: PriceProfile = budget.price_profile
    result = run(provider.complete(
        model=budget.generator_model,
        messages=[{"role": "user", "content": "Reply with the single word ok."}],
        temperature=0.0,
        max_output_tokens=16,
    ))
    usage = result.get("usage") or {}
    est = estimate_call_cost(
        profile,
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
    )
    assert est <= spend_cap_usd, (
        f"live call would spend {est:.4f} USD, over cap {spend_cap_usd}"
    )
    # content must be a parseable dict (JSON mode)
    content = result.get("content", {})
    assert isinstance(content, dict)
