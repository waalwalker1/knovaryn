"""Pricing profile and cost ledger (spec §11.7, §22.5).

Prices are dated, overridable provider metadata — never hard-coded domain
logic. Provider-reported usage is authoritative; costs are estimates unless the
provider reports a reconciled total.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...domain.errors import ConfigurationError


@dataclass
class PriceProfile:
    price_snapshot_date: str
    provider: str
    price_input_per_m: float = 0.0
    price_output_per_m: float = 0.0
    price_cached_input_per_m: float | None = None

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "PriceProfile":
        return cls(
            price_snapshot_date=cfg.get("price_snapshot_date", ""),
            provider=cfg.get("provider", "unknown"),
            price_input_per_m=float(cfg.get("price_input_per_m", 0.0)),
            price_output_per_m=float(cfg.get("price_output_per_m", 0.0)),
            price_cached_input_per_m=(float(cfg["price_cached_input_per_m"]) if cfg.get("price_cached_input_per_m") is not None else None),
        )


def estimate_call_cost(
    profile: PriceProfile,
    *,
    input_tokens: int = 0,
    cached_input_tokens: int = 0,
    output_tokens: int = 0,
) -> float:
    """Estimate cost in USD. Cached-input tokens, when exposed, use the cached rate."""
    input_tokens = max(0, input_tokens)
    cached_input_tokens = max(0, cached_input_tokens)
    output_tokens = max(0, output_tokens)

    input_cost = (input_tokens / 1_000_000) * profile.price_input_per_m
    if profile.price_cached_input_per_m is not None:
        input_cost = (cached_input_tokens / 1_000_000) * profile.price_cached_input_per_m + (
            (input_tokens - cached_input_tokens) / 1_000_000
        ) * profile.price_input_per_m
    output_cost = (output_tokens / 1_000_000) * profile.price_output_per_m
    return round(input_cost + output_cost, 6)


def build_cost_entry(
    *,
    provider: str,
    model: str,
    usage: dict[str, Any] | None,
    profile: PriceProfile | None,
    latency_ms: int = 0,
    retries: int = 0,
    provider_request_id: str | None = None,
) -> dict[str, Any]:
    """Normalize usage + computed estimate into a cost-ledger entry."""
    usage = usage or {}
    input_tokens = int(usage.get("input_tokens", 0))
    cached_input = int(usage.get("cached_input_tokens", 0) or usage.get("prompt_tokens_details", {}).get("cached_tokens", 0))
    output_tokens = int(usage.get("output_tokens", 0))
    est = estimate_call_cost(profile, input_tokens=input_tokens, cached_input_tokens=cached_input, output_tokens=output_tokens) if profile else 0.0
    return {
        "provider": provider,
        "model": model,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input,
        "output_tokens": output_tokens,
        "latency_ms": latency_ms,
        "retries": retries,
        "provider_request_id": provider_request_id,
        "price_snapshot_date": profile.price_snapshot_date if profile else None,
        "price_input_per_m": profile.price_input_per_m if profile else 0.0,
        "price_output_per_m": profile.price_output_per_m if profile else 0.0,
        "estimated_cost": est,
    }
