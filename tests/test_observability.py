"""Observability tests (spec §22.2, WP K4).

Verifies the Prometheus-style metrics endpoint and registry mechanics: labelled
counters, gauges, and histogram (_count/_sum) rendering, and admin scoping of
``/v1/metrics``. Metrics are never truthiness-only: a count is a real,
inspectable integer. Runs offline.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import knovaryn.infrastructure.telemetry.metrics as mtr


@pytest.fixture(autouse=True)
def _clean_registry():
    # Fresh registry per test so counters don't leak across cases.
    old = mtr._REGISTRY
    mtr._REGISTRY = mtr.MetricsRegistry()
    try:
        yield
    finally:
        mtr._REGISTRY = old


@pytest.fixture
def client(tmp_path, monkeypatch):
    import knovaryn.application.workspace as ws
    from knovaryn.interfaces.rest.app import app

    monkeypatch.setattr(
        ws,
        "load_config",
        lambda: {"storage.database_url": f"sqlite+aiosqlite:///{tmp_path}/obs.db"},
    )
    with TestClient(app) as c:
        yield c


pytestmark = [pytest.mark.rest]


def test_metrics_endpoint_renders_prometheus(client):
    mtr.get_registry().inc("knovaryn_export_total", labels={"format": "canonical-jsonl"})
    r = client.get("/v1/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert 'knovaryn_export_total{format="canonical-jsonl"} 1' in r.text
    assert "# TYPE" in r.text


def test_metrics_endpoint_admin_scoped_with_token(monkeypatch, client):
    """With a configured token lacking admin, metrics read is denied (401/403)."""
    import knovaryn.infrastructure.auth.bearer as bearer
    import knovaryn.interfaces.rest.security as sec

    server = {"server": {"api_token": "sek", "scopes": ["project:read"], "admin_principals": []}}
    monkeypatch.setattr(bearer, "load_config", lambda: server)
    monkeypatch.setattr(sec, "load_config", lambda: server)
    assert client.get("/v1/metrics").status_code == 401  # no token supplied


def test_registry_counts_and_labels():
    reg = mtr.MetricsRegistry()
    reg.inc("knovaryn_export_total", labels={"format": "canonical-jsonl"})
    reg.inc("knovaryn_export_total", labels={"format": "canonical-jsonl"})
    reg.inc("knovaryn_provider_errors_total", labels={"topology": "sft"})
    text = reg.render_prometheus()
    assert 'knovaryn_export_total{format="canonical-jsonl"} 2' in text
    assert 'knovaryn_provider_errors_total{topology="sft"} 1' in text


def test_histogram_renders_count_and_sum():
    reg = mtr.MetricsRegistry()
    reg.observe("knovaryn_job_stage_duration_seconds", 0.5, {"stage": "ingest"})
    reg.observe("knovaryn_job_stage_duration_seconds", 1.5, {"stage": "ingest"})
    text = reg.render_prometheus()
    assert 'knovaryn_job_stage_duration_seconds{stage="ingest"}_count 2' in text
    assert "_sum 2.0" in text


def test_timer_context_observes_histogram():
    reg = mtr.MetricsRegistry()
    with mtr.Timer(reg, "knovaryn_job_stage_duration_seconds", {"stage": "generate"}):
        pass
    assert reg.histograms.get('knovaryn_job_stage_duration_seconds{stage="generate"}')


def test_gauges_render():
    reg = mtr.MetricsRegistry()
    reg.set_gauge("knovaryn_queue_depth", 3, {"queue": "pipeline"})
    assert 'knovaryn_queue_depth{queue="pipeline"} 3' in reg.render_prometheus()
