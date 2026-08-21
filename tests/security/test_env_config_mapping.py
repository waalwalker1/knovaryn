"""Regression tests: operator env vars must reach the config they name.

The production compose files (and docs) configure the stack through flat
``KNOVARYN_*`` environment variables. v0.1's env collector split variable
names on underscores naively, so:

* ``KNOVARYN_API_TOKEN`` resolved to ``api.token`` — NOT ``server.api_token``;
  a container started with the documented token variable still refused to
  bind non-loopback (caught by the compose E2E, defect 4.11);
* ``KNOVARYN_STORAGE_DATABASE_URL`` resolved to ``storage.database.url`` —
  NOT ``storage.database_url``; the Postgres URL never reached the app.

Corrected contract: compound leaf keys and the implied-section token alias
resolve to the config paths operators (and the shipped compose files) mean.
"""

from __future__ import annotations

import pytest

from knovaryn.domain.config import load_config


@pytest.mark.unit
class TestEnvConfigMapping:
    """Documented KNOVARYN_* variables land on their named config paths."""

    def test_api_token_reaches_server_section(self, monkeypatch):
        monkeypatch.setenv("KNOVARYN_API_TOKEN", "tok-123")
        cfg = load_config()
        assert cfg.get("server.api_token") == "tok-123"

    def test_compound_storage_keys_resolve(self, monkeypatch):
        monkeypatch.setenv(
            "KNOVARYN_STORAGE_DATABASE_URL", "postgresql+asyncpg://db.example/knovaryn"
        )
        monkeypatch.setenv("KNOVARYN_STORAGE_ARTIFACT_BACKEND", "s3")
        cfg = load_config()
        assert cfg.get("storage.database_url") == "postgresql+asyncpg://db.example/knovaryn"
        assert cfg.get("storage.artifact_backend") == "s3"

    def test_plain_nested_names_still_work(self, monkeypatch):
        """Simple section_key names keep their existing mapping."""
        monkeypatch.setenv("KNOVARYN_TELEMETRY_CONTENT_IN_LOGS", "false")
        cfg = load_config()
        assert cfg.get("telemetry.content_in_logs") is False

    def test_file_value_overridden_by_env(self, monkeypatch, tmp_path):
        """Precedence: env beats config files (spec §20)."""
        cfg_file = tmp_path / "k.yaml"
        cfg_file.write_text("server:\n  api_token: from-file\n")
        monkeypatch.setenv("KNOVARYN_API_TOKEN", "from-env")
        cfg = load_config(paths=[str(cfg_file)])
        assert cfg.get("server.api_token") == "from-env"

    def test_full_compose_env_block_resolves(self, monkeypatch):
        """Every KNOVARYN_* var the shipped compose files set lands where
        ``build_artifact_store`` / the server read it."""
        monkeypatch.setenv("KNOVARYN_STORAGE_DATABASE_URL", "postgresql+asyncpg://db/knovaryn")
        monkeypatch.setenv("KNOVARYN_STORAGE_ARTIFACT_BACKEND", "s3")
        monkeypatch.setenv("KNOVARYN_STORAGE_BUCKET", "knovaryn-artifacts")
        monkeypatch.setenv("KNOVARYN_STORAGE_ENDPOINT_URL", "http://minio:9000")
        monkeypatch.setenv("KNOVARYN_STORAGE_REGION", "us-east-1")
        monkeypatch.setenv("KNOVARYN_STORAGE_ACCESS_KEY_ID", "minio-user")
        monkeypatch.setenv("KNOVARYN_STORAGE_SECRET_ACCESS_KEY", "minio-pass")
        monkeypatch.setenv("KNOVARYN_TELEMETRY_CONTENT_IN_LOGS", "false")
        cfg = load_config()
        assert cfg.get("storage.database_url") == "postgresql+asyncpg://db/knovaryn"
        assert cfg.get("storage.artifact_backend") == "s3"
        assert cfg.get("storage.bucket") == "knovaryn-artifacts"
        assert cfg.get("storage.endpoint_url") == "http://minio:9000"
        assert cfg.get("storage.region") == "us-east-1"
        assert cfg.get("storage.access_key_id") == "minio-user"
        assert cfg.get("storage.secret_access_key") == "minio-pass"
        assert cfg.get("telemetry.content_in_logs") is False

    def test_env_bool_coercion_is_real_bool(self, monkeypatch):
        """``KNOVARYN_X=false`` must not be a truthy string."""
        monkeypatch.setenv("KNOVARYN_SERVER_ALLOW_INSECURE_NONLOOPBACK", "true")
        cfg = load_config()
        assert cfg.get("server.allow_insecure_nonloopback") is True
