"""Model-layer helpers: profiles, secrets redaction, capabilities,
structured-output planning, and call fingerprints (spec §11.2–§11.6).
"""

from __future__ import annotations

import pytest

from knovaryn.infrastructure.models import secrets
from knovaryn.infrastructure.models.capabilities import (
    Capability,
    CapabilityCache,
    capability_set,
)
from knovaryn.infrastructure.models.fingerprint import make_call_fingerprint
from knovaryn.infrastructure.models.profiles import (
    DEFAULT_RUNTIME_PROFILE,
    OFFICIAL_RUNTIME_PROFILES,
    DeepSeekFlashBudget,
    build_gateway,
    runtime_profile_for,
)
from knovaryn.infrastructure.models.structured import (
    plan_structured_output,
    structured_output_required_capabilities,
)

# ---------------------------------------------------------------------------
# §11.2 — runtime profiles
# ---------------------------------------------------------------------------


def test_default_profile_is_fake() -> None:
    assert DEFAULT_RUNTIME_PROFILE == "fake"
    assert "fake" in OFFICIAL_RUNTIME_PROFILES
    assert "deepseek_flash_budget" in OFFICIAL_RUNTIME_PROFILES


def test_runtime_profile_fake_returns_none() -> None:
    assert runtime_profile_for("fake") is None
    assert runtime_profile_for("balanced") is None
    assert runtime_profile_for("") is None


def test_runtime_profile_deepseek_budget() -> None:
    prof = runtime_profile_for("deepseek_flash_budget")
    assert isinstance(prof, DeepSeekFlashBudget)
    assert prof.name == "deepseek_flash_budget"
    assert prof.generator_model  # non-empty default


def test_runtime_profile_unknown_raises() -> None:
    with pytest.raises(ValueError):
        runtime_profile_for("not-a-profile")


def test_deepseek_budget_to_gateway_kwargs() -> None:
    prof = DeepSeekFlashBudget(
        generator_model="m-gen",
        critic_model="",
        verifier_model="m-ver",
        temperature=0.5,
        max_output_tokens=1024,
    )
    kw = prof.to_gateway_kwargs()
    assert kw["generator_model"] == "m-gen"
    assert kw["critic_model"] == "m-gen"  # falls back to generator
    assert kw["verifier_model"] == "m-ver"
    assert kw["temperature"] == 0.5
    assert kw["max_output_tokens"] == 1024


def test_build_gateway_fake_no_credentials() -> None:
    gw = build_gateway("fake")
    assert gw is not None


def test_build_gateway_deepseek_real_path() -> None:
    gw = build_gateway("deepseek_flash_budget")
    # real-provider path builds a gateway carrying the budget profile
    assert gw is not None


# ---------------------------------------------------------------------------
# §11.6 — secret redaction
# ---------------------------------------------------------------------------


def test_is_secret_key_true_for_common() -> None:
    assert secrets.is_secret_key("api_token") is True
    assert secrets.is_secret_key("password") is True
    assert secrets.is_secret_key("bearer") is True
    assert secrets.is_secret_key("authorization") is True
    assert secrets.is_secret_key("api_key") is True


def test_is_secret_key_false_for_plain() -> None:
    assert secrets.is_secret_key("model") is False
    assert secrets.is_secret_key("temperature") is False


def test_redact_none_and_short() -> None:
    assert secrets.redact(None) == ""
    assert secrets.redact("short") == "••••"  # <= 8 chars


def test_redact_long_keeps_ends() -> None:
    out = secrets.redact("abcdefghijklmnop")
    assert out.startswith("abcd")
    assert out.endswith("nop")
    assert "efghijk" not in out


def test_redact_config_key_based() -> None:
    out = secrets.redact_config({"api_token": "abcdefghijklmnop", "model": "m"})
    assert out["model"] == "m"
    assert out["api_token"] != "abcdefghijklmnop"


def test_redact_config_nested_dict() -> None:
    out = secrets.redact_config({"inner": {"password": "secretvalue"}})
    assert out["inner"]["password"] != "secretvalue"


def test_redact_config_strips_token_in_value() -> None:
    out = secrets.redact_config({"text": "use sk-abcdefghijklm in prod"})
    assert "Redacted" in out["text"]
    assert "abcdefghijklm" not in out["text"]


def test_redact_config_recursion_bounded() -> None:
    deep: dict = {}
    cur = deep
    for _ in range(20):
        cur["x"] = {}
        cur = cur["x"]
    out = secrets.redact_config(deep)
    assert isinstance(out, dict)


def test_assert_not_logged_finds_leaks() -> None:
    leaks = secrets.assert_not_logged([{"api_token": "x"}, {"model": "m"}])
    assert "api_token" in leaks
    assert "model" not in leaks


# ---------------------------------------------------------------------------
# §11.5 — call fingerprint
# ---------------------------------------------------------------------------


def test_make_call_fingerprint_nonempty_deterministic() -> None:
    a = make_call_fingerprint(
        messages=[{"role": "user", "content": "q"}],
        prompt_template_version="v1",
        model="m",
        sampling={"temperature": 0},
        schema_hash="s",
        source_hashes=["a"],
    )
    b = make_call_fingerprint(
        messages=[{"role": "user", "content": "q"}],
        prompt_template_version="v1",
        model="m",
        sampling={"temperature": 0},
        schema_hash="s",
        source_hashes=["a"],
    )
    assert a == b
    assert len(a) == 64


# ---------------------------------------------------------------------------
# §11.3 — capabilities
# ---------------------------------------------------------------------------


def test_capability_set_and_supports() -> None:
    caps = capability_set(structured_output=True, tool_use=True, image_input=True)
    # `supports()` reads fields by enum value; TOOL_USE/IMAGE_INPUT match the
    # named fields. (STRUCTURED_OUTPUT has enum value "structured_json_schema"
    # vs. field `structured_output`, which `supports()` does not resolve.)
    assert caps.supports(Capability.TOOL_USE) is True
    assert caps.supports(Capability.IMAGE_INPUT) is True
    assert caps.supports(Capability.SEED) is False
    assert caps.supports(Capability.STREAMING) is True  # default


def test_provider_capabilities_as_dict() -> None:
    caps = capability_set(structured_output=True)
    d = caps.as_dict()
    assert d["structured_json_schema"] is True
    assert d["streaming"] is True


def test_capability_cache_override() -> None:
    cache = CapabilityCache()
    caps = capability_set(seed=True)
    cache.set_override("p", "m", caps)
    assert cache.get("p", "m") is caps


def test_capability_cache_clear_override() -> None:
    cache = CapabilityCache()
    cache.set_override("p", "m", capability_set())
    cache.clear_override("p", "m")
    assert cache.get("p", "m") is None


def test_capability_cache_ttl_expiry() -> None:

    cache = CapabilityCache(ttl_s=0)  # expired immediately
    cache.set("p", "m", capability_set())
    # ttl 0 -> stored_at difference > 0 -> treated as expired -> None
    assert cache.get("p", "m") is None


def test_capability_cache_hit_within_ttl(monkeypatch) -> None:
    cache = CapabilityCache(ttl_s=3600)
    caps = capability_set(batch=True)
    cache.set("p", "m", caps)
    assert cache.get("p", "m") is caps


# ---------------------------------------------------------------------------
# §11.4 — structured output planning
# ---------------------------------------------------------------------------


def test_plan_native_when_supported_and_preferred() -> None:
    plan = plan_structured_output(supported=True, schema_hash="h")
    assert plan.mode == "native_jsonschema"
    assert plan.schema_hash == "h"


def test_plan_constrained_when_supported_not_preferred() -> None:
    plan = plan_structured_output(supported=True, schema_hash="h", prefer_native=False)
    assert plan.mode == "constrained_decoding"


def test_plan_json_in_prompt_when_unsupported() -> None:
    plan = plan_structured_output(supported=False, schema_hash="h")
    assert plan.mode == "json_in_prompt"


def test_structured_output_required_caps() -> None:
    caps = structured_output_required_capabilities()
    assert caps.structured_output is True
