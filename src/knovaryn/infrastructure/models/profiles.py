"""Runtime model profiles (spec §11.2, exec rule 22).

Framework-free profile registry that isolates model-role and pricing choices
behind the :class:`ModelGateway` provider abstraction. CI and the offline demo
stay on the deterministic :class:`FakeProvider`; a live provider is only used
when the operator selects a real profile and supplies credentials.

The ``deepseek_flash_budget`` profile is a *runtime* budget profile: it wires
DeepSeek-V4-Flash (or the operator's configured model via
``KNOVARYN_GENERATOR_MODEL``) with a *dated* ``PriceProfile`` snapshot. Prices
are recorded with a snapshot date and are never treated as permanent domain
logic — see ``docs/adr/0005-litellm-and-providers.md``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from ...identity import ENV_PREFIX
from .cost import PriceProfile

# Keep the offline/CI path on the deterministic fake provider unless the
# operator explicitly enables a live profile.
DEFAULT_RUNTIME_PROFILE = "fake"

# Official, recognized runtime profiles. ``deepseek_flash_budget`` is a
# first-class budget profile; others may be added without touching domain code.
OFFICIAL_RUNTIME_PROFILES = {"fake", "deepseek_flash_budget"}


def _env(name: str, default: str = "") -> str:
    return os.environ.get(f"{ENV_PREFIX}{name}", default)


@dataclass
class DeepSeekFlashBudget:
    """Budget-oriented DeepSeek-V4-Flash runtime profile (dated pricing)."""

    name: str = "deepseek_flash_budget"
    generator_model: str = field(
        default_factory=lambda: _env("GENERATOR_MODEL", "deepseek-v4-flash")
    )
    critic_model: str = field(default_factory=lambda: _env("CRITIC_MODEL", ""))
    verifier_model: str = field(default_factory=lambda: _env("VERIFIER_MODEL", ""))
    temperature: float = 0.3
    max_output_tokens: int = 2400
    price_profile: PriceProfile = field(
        default_factory=lambda: PriceProfile(
            price_snapshot_date="2026-08-01",
            provider="deepseek",
            price_input_per_m=0.07,
            price_output_per_m=0.28,
            price_cached_input_per_m=0.014,
        )
    )

    def to_gateway_kwargs(self) -> dict[str, Any]:
        return {
            "generator_model": self.generator_model,
            "critic_model": self.critic_model or self.generator_model,
            "verifier_model": self.verifier_model or self.generator_model,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "price_profile": self.price_profile,
        }


def runtime_profile_for(name: str) -> Any:
    """Return a runtime profile object for a recognized profile name.

    ``fake`` returns None (the gateway already defaults to the fake provider);
    ``deepseek_flash_budget`` returns a :class:`DeepSeekFlashBudget`.
    """
    if name == "deepseek_flash_budget":
        return DeepSeekFlashBudget()
    if name in ("fake", "balanced", "fast-local", "high-quality", "air-gapped", "enterprise", ""):
        return None
    raise ValueError(f"unknown runtime profile: {name}")


def build_gateway(profile: str | None = None, **overrides: Any):
    """Build a :class:`ModelGateway` for a runtime profile.

    Offline/CI (fake, balanced, or default) yields a fake-only gateway with no
    credentials. ``deepseek_flash_budget`` yields a real-provider-capable
    gateway carrying the dated DeepSeek price profile.
    """
    from .gateway import ModelGateway

    name = profile or DEFAULT_RUNTIME_PROFILE
    if name == "deepseek_flash_budget":
        prof = DeepSeekFlashBudget()
        from .litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider(api_base=_env("DEEPSEEK_BASE_URL") or None)
        kwargs: dict[str, Any] = prof.to_gateway_kwargs()
        kwargs.update(overrides)
        return ModelGateway(real_provider=provider, **kwargs)
    # offline / fake path — no credentials required
    return ModelGateway(**overrides)


__all__ = [
    "DEFAULT_RUNTIME_PROFILE",
    "OFFICIAL_RUNTIME_PROFILES",
    "DeepSeekFlashBudget",
    "runtime_profile_for",
    "build_gateway",
]
