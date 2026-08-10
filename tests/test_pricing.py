"""Pricing policy (spec §11.7, exec rule: never hard-code provider prices).

Prices must be dated, configurable metadata — not hard-coded domain logic —
and must never be pinned to a specific provider (e.g. DeepSeek) in the core.
"""

from __future__ import annotations

import inspect

from knovaryn.infrastructure.models import cost


def test_cost_module_has_no_hardcoded_deepseek_price() -> None:
    src = inspect.getsource(cost)
    # The module must not hard-code a DeepSeek model price as a default rate.
    assert "deepseek" not in src.lower()


def test_price_comes_from_config_not_constant() -> None:
    profile = cost.PriceProfile.from_config(
        {
            "price_snapshot_date": "2026-08-01",
            "provider": "some-host",
            "price_input_per_m": 1.0,
            "price_output_per_m": 2.0,
        }
    )
    assert profile.price_input_per_m == 1.0
    assert profile.price_output_per_m == 2.0


def test_estimate_call_cost_uses_profile_rates() -> None:
    profile = cost.PriceProfile(
        price_snapshot_date="2026-08-01",
        provider="some-host",
        price_input_per_m=1.0,
        price_output_per_m=2.0,
    )
    est = cost.estimate_call_cost(profile, input_tokens=1_000_000, output_tokens=500_000)
    # 1.0 * 1.0 + 0.5 * 2.0 = 2.0
    assert est == 2.0


def test_zero_profile_estimates_zero() -> None:
    profile = cost.PriceProfile(
        price_snapshot_date="2026-08-01",
        provider="none",
        price_input_per_m=0.0,
        price_output_per_m=0.0,
    )
    assert cost.estimate_call_cost(profile, input_tokens=10_000, output_tokens=10_000) == 0.0
