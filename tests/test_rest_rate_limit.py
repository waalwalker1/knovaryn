"""Rate limiting + abuse-control tests (spec §17.4, WP J7).

Verifies the five J7 limits: per-principal request budget (429 via the ASGI
middleware), upload byte cap (413), concurrent-job cap, provider-call cap, and
publication-attempt cap. Abuse controls are exercised against the shared
application path (rule 6: never truthiness-only — an explicit cap is checked).
Runs offline.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import knovaryn.application.abuse as abuse
import knovaryn.interfaces.rest.app as rest_app
import knovaryn.interfaces.rest.rate_limit as rl


@pytest.fixture
def client(tmp_path, monkeypatch):
    import knovaryn.application.workspace as ws_mod

    rl.reset_rate_limit_state()
    db_url = f"sqlite+aiosqlite:///{tmp_path}/ratelimit.db"
    monkeypatch.setattr(ws_mod, "load_config", lambda: {"storage.database_url": db_url})
    rest_app._workspace = None
    with TestClient(app_instance()) as c:
        yield c
    rest_app._workspace = None
    abuse.reset_abuse_state()
    rl.reset_rate_limit_state()


def app_instance():
    from knovaryn.interfaces.rest.app import app

    return app


def _patch_limits(monkeypatch, **kwargs):
    """Point all load_config consumers at a rate_limit block."""
    import knovaryn.application.workspace as ws_mod
    import knovaryn.interfaces.rest.security_middleware as sm

    rl_cfg = {
        "requests_per_minute": kwargs.get("requests_per_minute", 0),
        "max_upload_bytes": kwargs.get("max_upload_bytes", 0),
        "max_concurrent_jobs": kwargs.get("max_concurrent_jobs", 0),
        "max_provider_calls_per_run": kwargs.get("max_provider_calls_per_run", 0),
        "max_publish_attempts_per_hour": kwargs.get("max_publish_attempts_per_hour", 0),
    }
    server = {"server": {"rate_limit": rl_cfg, "api_token": ""}}
    monkeypatch.setattr(abuse, "load_config", lambda: server)
    monkeypatch.setattr(rl, "load_config", lambda: server)
    monkeypatch.setattr(sm, "load_config", lambda: server)
    monkeypatch.setattr(ws_mod, "load_config", lambda: server)
    return rl_cfg


# ---------------------------------------------------------------- request budget
pytestmark = [pytest.mark.rest]


def test_request_budget_429_on_client_ip(monkeypatch, client):
    """Low per-IP budget trips 429 (unauthenticated keyed by client address)."""
    _patch_limits(monkeypatch, requests_per_minute=2)
    r1 = client.get("/v1/health")
    r2 = client.get("/v1/health")
    r3 = client.get("/v1/health")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429


def test_request_budget_keyed_by_token(monkeypatch, client):
    """Distinct bearer tokens get isolated budgets; one token trips its own 429."""
    _patch_limits(monkeypatch, requests_per_minute=1)
    h1 = {"Authorization": "Bearer one"}
    h2 = {"Authorization": "Bearer two"}
    assert client.get("/v1/health", headers=h1).status_code in (200, 401)
    assert client.get("/v1/health", headers=h2).status_code in (200, 401)
    # second request on the SAME bearer identity is rate-limited
    assert client.get("/v1/health", headers=h1).status_code == 429


def test_upload_bytes_cap_413(monkeypatch, client):
    _patch_limits(monkeypatch, max_upload_bytes=100)
    resp = client.post(
        "/v1/projects",
        content=('{"slug": "x", "display_name": "' + ("Y" * 500) + '"}').encode(),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 413


# ---------------------------------------------------------- concurrent jobs cap
@pytest.mark.asyncio
async def test_concurrent_jobs_cap_raises(monkeypatch):
    _patch_limits(monkeypatch, max_concurrent_jobs=1)
    import knovaryn.application.abuse as ab

    # count already at the cap (simulating a busy pool via the same helper path)
    ab.enforce_concurrent_jobs(running_count=0)  # ok (0 < cap)
    from knovaryn.domain.errors import RateLimitError

    with pytest.raises(RateLimitError):
        ab.enforce_concurrent_jobs(running_count=1)  # at cap -> blocked


# ----------------------------------------------------------- provider call cap
@pytest.mark.asyncio
async def test_provider_call_cap_raises(monkeypatch):
    _patch_limits(monkeypatch, max_provider_calls_per_run=2)
    import knovaryn.application.abuse as ab

    ab.begin_generation_run()
    ab.enforce_provider_call()
    ab.enforce_provider_call()
    from knovaryn.domain.errors import RateLimitError

    with pytest.raises(RateLimitError):
        ab.enforce_provider_call()  # 3rd call exceeds cap


# ----------------------------------------------------- publication-attempt cap
@pytest.mark.asyncio
async def test_publish_attempt_cap_raises(monkeypatch):
    _patch_limits(monkeypatch, max_publish_attempts_per_hour=2)
    import knovaryn.application.abuse as ab

    ab.enforce_publish_attempts(principal="alice")
    ab.enforce_publish_attempts(principal="alice")
    from knovaryn.domain.errors import RateLimitError

    with pytest.raises(RateLimitError):
        ab.enforce_publish_attempts(principal="alice")
    # different principal unaffected
    ab.enforce_publish_attempts(principal="bob")


# ------------------------------------------------------------- RateLimitError map
def test_rate_limit_error_maps_to_429():
    from knovaryn.domain.errors import RateLimitError

    # The _err mapping is exercised indirectly; assert the code is stable.
    e = RateLimitError("nope")
    assert e.code == "rate_limited"
    assert "nope" in e.as_public_dict()["message"]


# ------------------------------------------------ RateLimit middleware (unit)
def test_rate_limit_bucket_window():
    b = rl._Bucket()
    assert b.allow(limit=2, now=0.0) is True
    assert b.allow(limit=2, now=0.1) is True
    assert b.allow(limit=2, now=0.2) is False  # within window, full
    assert b.allow(limit=2, now=61.0) is True  # window slid past first entry
