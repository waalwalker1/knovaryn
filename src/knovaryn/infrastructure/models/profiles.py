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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .gateway import ModelGateway

from ...domain.errors import ConfigurationError
from ...identity import ENV_PREFIX
from .cost import PriceProfile

# Keep the offline/CI path on the deterministic fake provider unless the
# operator explicitly enables a live profile.
DEFAULT_RUNTIME_PROFILE = "fake"

# Official, recognized runtime profiles. ``deepseek_flash_budget`` is a
# first-class budget profile; others may be added without touching domain code.
# The set is the union of the config-side official profiles and the contract
# (WP D4) runtime profile names, so configuration and gateway accept the same
# vocabulary and DeepSeek is never hard-coded as the product identity.
OFFICIAL_RUNTIME_PROFILES = {
    # offline / fake
    "fake",
    "offline-demo",
    "fast-local",
    "balanced",
    "air-gapped",
    # live, budget or task-tuned
    "deepseek_flash_budget",
    "deepseek-budget",
    "local-openai-compatible",
    "anthropic-quality",
    "openai-quality",
    "gemini-quality",
    "custom-litellm",
    "high-quality",
    "enterprise",
}


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


@dataclass
class LiveProviderProfile:
    """Generic live-provider runtime profile (WP D4).

    Wires a real OpenAI-compatible provider entirely from environment
    configuration. No vendor is hard-coded as the product identity; the base
    URL, model, and pricing all come from operator environment so any
    OpenAI-compatible endpoint (local, Anthropic-compatible, OpenAI, Gemini,
    custom LiteLLM router) is the operator's choice. Pricing is a *dated*
    ``PriceProfile`` snapshot, never permanent domain logic.
    """

    name: str
    default_model: str
    price_snapshot_date: str
    price_input_per_m: float
    price_output_per_m: float
    price_cached_input_per_m: float = 0.0

    def to_gateway_kwargs(self) -> dict[str, Any]:
        gen = _env("GENERATOR_MODEL", self.default_model)
        return {
            "generator_model": gen,
            "critic_model": _env("CRITIC_MODEL", gen),
            "verifier_model": _env("VERIFIER_MODEL", gen),
            "temperature": float(_env("TEMPERATURE", "0.3")),
            "max_output_tokens": int(_env("MAX_OUTPUT_TOKENS", "2400")),
            "price_profile": PriceProfile(
                price_snapshot_date=self.price_snapshot_date,
                provider=self.name,
                price_input_per_m=self.price_input_per_m,
                price_output_per_m=self.price_output_per_m,
                price_cached_input_per_m=self.price_cached_input_per_m,
            ),
        }


def _live_profile(name: str) -> LiveProviderProfile:
    defaults = {
        # base URL / credentials come from KNOVARYN_* env; provider is generic.
        "local-openai-compatible": LiveProviderProfile(
            name=name,
            default_model=_env("LOCAL_MODEL", "local-model"),
            price_snapshot_date="2026-08-01",
            price_input_per_m=0.0,
            price_output_per_m=0.0,
        ),
        "anthropic-quality": LiveProviderProfile(
            name=name,
            default_model=_env("ANTHROPIC_MODEL", "anthropic-quality-model"),
            price_snapshot_date="2026-08-01",
            price_input_per_m=3.0,
            price_output_per_m=15.0,
            price_cached_input_per_m=0.3,
        ),
        "openai-quality": LiveProviderProfile(
            name=name,
            default_model=_env("OPENAI_MODEL", "openai-quality-model"),
            price_snapshot_date="2026-08-01",
            price_input_per_m=2.5,
            price_output_per_m=10.0,
            price_cached_input_per_m=1.25,
        ),
        "gemini-quality": LiveProviderProfile(
            name=name,
            default_model=_env("GEMINI_MODEL", "gemini-quality-model"),
            price_snapshot_date="2026-08-01",
            price_input_per_m=1.25,
            price_output_per_m=5.0,
            price_cached_input_per_m=0.0,
        ),
        "custom-litellm": LiveProviderProfile(
            name=name,
            default_model=_env("CUSTOM_MODEL", _env("GENERATOR_MODEL", "custom-model")),
            price_snapshot_date="2026-08-01",
            price_input_per_m=float(_env("PRICE_INPUT_PER_M", "0.0")),
            price_output_per_m=float(_env("PRICE_OUTPUT_PER_M", "0.0")),
            price_cached_input_per_m=float(_env("PRICE_CACHED_INPUT_PER_M", "0.0")),
        ),
        "high-quality": LiveProviderProfile(
            name=name,
            default_model=_env("GENERATOR_MODEL", "high-quality-model"),
            price_snapshot_date="2026-08-01",
            price_input_per_m=5.0,
            price_output_per_m=20.0,
        ),
        "enterprise": LiveProviderProfile(
            name=name,
            default_model=_env("GENERATOR_MODEL", "enterprise-model"),
            price_snapshot_date="2026-08-01",
            price_input_per_m=8.0,
            price_output_per_m=30.0,
        ),
    }
    profile = defaults.get(name)
    if profile is None:
        raise ValueError(f"unknown runtime profile: {name}")
    return profile


def runtime_profile_for(name: str) -> Any:
    """Return a runtime profile object for a recognized profile name.

    Offline names (``fake`` and config-side offline aliases) return None (the
    gateway already defaults to the fake provider); live names return a
    :class:`LiveProviderProfile` (or :class:`DeepSeekFlashBudget`).
    """
    if name == "deepseek_flash_budget":
        return DeepSeekFlashBudget()
    if name == "deepseek-budget":
        return DeepSeekFlashBudget()
    if name == "":
        return None
    if name in OFFICIAL_RUNTIME_PROFILES and name not in _LIVE_NAMES:
        return None
    if name in _LIVE_NAMES:
        return _live_profile(name)
    raise ValueError(f"unknown runtime profile: {name}")


_LIVE_NAMES = {
    "local-openai-compatible",
    "anthropic-quality",
    "openai-quality",
    "gemini-quality",
    "custom-litellm",
    "high-quality",
    "enterprise",
    "deepseek_flash_budget",
    "deepseek-budget",
}


def _require_live_credentials(profile_name: str) -> None:
    """Refuse to wire a live profile without any credential signal (defect 4.9).

    A live profile selected with no credentials anywhere in the environment
    almost always means a misconfiguration. v0.1 wired such selections to the
    fake gateway anyway — the worst kind of silent fake fallback (the operator
    believes they paid for real generation). We fail loudly instead; the
    ModelGateway itself still refuses per-call fake fallback (WP D5) as the
    second line of defence.
    """
    signals = (
        _env("DEEPSEEK_API_KEY"),
        _env("API_KEY"),
        _env("BASE_URL"),
        _env("DEEPSEEK_BASE_URL"),
    )
    if not any(signals):
        raise ConfigurationError(
            f"runtime profile {profile_name!r} is a live profile but no provider "
            f"credentials are configured (set one of KNOVARYN_DEEPSEEK_API_KEY, "
            f"KNOVARYN_API_KEY, KNOVARYN_BASE_URL, KNOVARYN_DEEPSEEK_BASE_URL). "
            f"Refusing to wire profile {profile_name!r}: never silently falling "
            f"back to the fake provider — choose an offline profile "
            f"({', '.join(sorted(OFFICIAL_RUNTIME_PROFILES - _LIVE_NAMES))}) for "
            f"deterministic offline operation."
        )


def build_gateway(profile: str | None = None, **overrides: Any) -> ModelGateway:
    """Build a :class:`ModelGateway` for a runtime profile.

    Offline profiles yield a fake-only gateway with no credentials. Live
    profiles yield a real-provider-capable gateway wired from operator
    environment, carrying a dated price profile — and raise
    :class:`ConfigurationError` when no credential signal exists (never a
    silent fake fallback).
    """
    from .gateway import ModelGateway

    name = profile or DEFAULT_RUNTIME_PROFILE
    if name in ("deepseek_flash_budget", "deepseek-budget"):
        _require_live_credentials(name)
        prof = DeepSeekFlashBudget()
        from .litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider(api_base=_env("DEEPSEEK_BASE_URL") or None)
        kwargs: dict[str, Any] = prof.to_gateway_kwargs()
        kwargs.update(overrides)
        return ModelGateway(real_provider=provider, profile=name, **kwargs)
    if name in _LIVE_NAMES:
        _require_live_credentials(name)
        lprof: LiveProviderProfile = _live_profile(name)
        from .litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider(api_base=_env("BASE_URL") or None)
        kwargs = lprof.to_gateway_kwargs()
        kwargs.update(overrides)
        return ModelGateway(real_provider=provider, profile=name, **kwargs)
    # offline / fake path — no credentials required
    return ModelGateway(profile="fake", **overrides)


__all__ = [
    "DEFAULT_RUNTIME_PROFILE",
    "OFFICIAL_RUNTIME_PROFILES",
    "DeepSeekFlashBudget",
    "runtime_profile_for",
    "build_gateway",
]
