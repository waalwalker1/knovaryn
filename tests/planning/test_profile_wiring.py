"""Regression tests: runtime profile wiring (defect 4.9).

The config declares ``models.profile`` and the profile registry exists, but
v0.1 wired every interface to a hard-coded fake gateway: selecting a live
profile was silently ignored (the worst kind of fake fallback — the operator
believes they paid for real generation). These tests pin the corrected
contract:

* a live profile selection must reach the gateway (real provider, real model);
* a live profile without credentials must fail LOUDLY at wiring time — never
  silently fall back to fake (spec §11.5, exec rule 2);
* the offline profiles remain explicit fake (offline-first product);
* the durable worker path wires the configured/requested profile through the
  same factory, keeping the crash-safe CallCache + model_calls ledger.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from knovaryn.application.workspace import Workspace
from knovaryn.domain.errors import ConfigurationError
from knovaryn.infrastructure.models.profiles import build_gateway


def _isolate_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every credential/profile env var so tests are hermetic."""
    for var in (
        "KNOVARYN_MODELS_PROFILE",
        "KNOVARYN_PROFILE",
        "KNOVARYN_DEEPSEEK_API_KEY",
        "KNOVARYN_DEEPSEEK_BASE_URL",
        "KNOVARYN_BASE_URL",
        "KNOVARYN_API_KEY",
        "KNOVARYN_GENERATOR_MODEL",
        "KNOVARYN_CRITIC_MODEL",
        "KNOVARYN_VERIFIER_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)


class TestProfileWiring:
    """Runtime profile must thread through the workspace/worker gateways."""

    async def test_profile_changes_model(self, monkeypatch, tmp_path):
        _isolate_provider_env(monkeypatch)
        monkeypatch.setenv("KNOVARYN_MODELS_PROFILE", "deepseek_flash_budget")
        monkeypatch.setenv("KNOVARYN_DEEPSEEK_API_KEY", "test-key-not-real")

        ws = Workspace(database_url=f"sqlite+aiosqlite:///{tmp_path}/pw.db")
        svc = ws.default_project_service()
        gw = svc._gateway
        assert gw.profile == "deepseek_flash_budget"
        assert gw.generator_model == "deepseek-v4-flash", (
            f"live profile must select the live model, got {gw.generator_model!r}"
        )
        assert gw._real is not None, "live profile must wire a real provider"

        # env model override is honored for generic live profiles too
        monkeypatch.setenv("KNOVARYN_MODELS_PROFILE", "openai-quality")
        monkeypatch.setenv("KNOVARYN_GENERATOR_MODEL", "gpt-test-large")
        gw2 = build_gateway("openai-quality")
        assert gw2.generator_model == "gpt-test-large"

    async def test_no_silent_fake_fallback(self, monkeypatch, tmp_path):
        _isolate_provider_env(monkeypatch)
        # a live profile with NO credentials must fail loudly at wiring time
        with pytest.raises(ConfigurationError, match="deepseek_flash_budget"):
            build_gateway("deepseek_flash_budget")
        ws = Workspace(database_url=f"sqlite+aiosqlite:///{tmp_path}/pw2.db")
        monkeypatch.setenv("KNOVARYN_MODELS_PROFILE", "openai-quality")
        with pytest.raises(ConfigurationError):
            ws.default_project_service()

        # offline profiles remain explicit fake (no credentials, no surprise)
        for offline in ("fake", "offline-demo", "balanced", "air-gapped"):
            gw = build_gateway(offline)
            assert gw.generator_model == "fake", f"{offline} must stay offline"
            assert gw._real is None

    async def test_worker_stage_uses_configured_profile(self, monkeypatch):
        """The durable worker path resolves profile: request > config, and keeps
        the crash-safe CallCache + model_calls ledger wired (spec §11.5)."""
        from knovaryn.interfaces.cli.commands import build_pipeline_gateway

        _isolate_provider_env(monkeypatch)
        cfg = {"models": {"profile": "balanced"}, "storage": {}}
        ids = SimpleNamespace()  # ledger repo is lazy; never touched here
        job = SimpleNamespace(id="job-1", project_id="proj-1", input={"pipeline": {}})
        gw = build_pipeline_gateway(cfg, db=None, ids=ids, job=job)
        assert gw.generator_model == "fake"  # balanced = offline alias
        assert gw._cache is not None and gw._model_call_repo is not None

        # request-level profile (job input) overrides config — spec §20
        monkeypatch.setenv("KNOVARYN_DEEPSEEK_API_KEY", "test-key-not-real")
        job.input["pipeline"]["profile"] = "deepseek_flash_budget"
        gw_live = build_pipeline_gateway(cfg, db=None, ids=ids, job=job)
        assert gw_live.profile == "deepseek_flash_budget"
        assert gw_live.generator_model == "deepseek-v4-flash"
        assert gw_live._real is not None
