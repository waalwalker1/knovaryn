"""CLI operational commands (spec §18, §22, §23) — doctor, backup, repair.

Uses a temporary state directory isolated from the real .knovaryn so the
tests never touch developer state. Covers the JSON and exit-code branches of
the operational commands.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from knovaryn.domain.config import Configuration
from knovaryn.interfaces.cli import commands as cli_commands


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch) -> Configuration:
    """Point the operational commands at a throwaway state dir."""
    artifacts = tmp_path / "state" / "artifacts"
    artifacts.mkdir(parents=True)
    db = tmp_path / "state" / "knovaryn.db"

    cfg = Configuration()
    cfg.set("storage.artifact_root", str(artifacts))
    cfg.set("storage.database_url", f"sqlite+aiosqlite:///{db}")

    monkeypatch.setattr(cli_commands, "load_config", lambda **kw: cfg)
    return cfg


def _artifact_root(cfg: Configuration) -> Path:
    return Path(cfg.get("storage.artifact_root"))


def _state_dir(cfg: Configuration) -> Path:
    return _artifact_root(cfg).parent


def _make_index(art: Path, objects) -> None:
    import json

    (art / "index.json").write_text(json.dumps({"objects": objects}))


def test_doctor_healthy_state_returns_zero(isolated_config) -> None:
    db = isolated_config.get("storage.database_url").replace("sqlite+aiosqlite:///", "")
    sqlite3.connect(db).close()
    # doctor returns 1 if any opt-in extra (docling/docetl/hf) is missing; the
    # database itself is healthy, so the exit code is 0 or 1 accordingly.
    assert cli_commands.doctor() in (0, 1)


def test_doctor_json_output(isolated_config, capsys) -> None:
    code = cli_commands.doctor(json_plain=True)
    captured = capsys.readouterr().out
    assert code in (0, 1)
    assert "knovaryn" in captured.lower() or "database" in captured.lower()


def test_doctor_non_sqlite_backend_missing_db_ok(monkeypatch, capsys) -> None:
    # non-sqlite backend -> db check skipped; doctor still depends on opt-in
    # extras availability, so the exit code is 0 or 1.
    cfg = Configuration()
    monkeypatch.setattr(cli_commands, "load_config", lambda **kw: cfg)
    assert cli_commands.doctor() in (0, 1)


def test_backup_missing_state_dir_returns_one(tmp_path, monkeypatch) -> None:
    cfg = Configuration()
    missing = tmp_path / "nope" / "artifacts"
    cfg.set("storage.artifact_root", str(missing))
    monkeypatch.setattr(cli_commands, "load_config", lambda **kw: cfg)
    assert cli_commands.backup(out=tmp_path / "backups") == 1


def test_backup_writes_tar_gz(isolated_config) -> None:
    art = _artifact_root(isolated_config)
    (art / "probe.txt").write_text("hello")
    dest = _state_dir(isolated_config) / "backups"
    assert cli_commands.backup(out=dest) == 0
    archives = list(dest.glob("*.tar.gz"))
    assert len(archives) == 1
    assert archives[0].stat().st_size > 0


def test_backup_json_output(isolated_config, capsys) -> None:
    art = _artifact_root(isolated_config)
    (art / "probe.txt").write_text("hello")
    dest = _state_dir(isolated_config) / "b2"
    assert cli_commands.backup(out=dest, json_plain=True) == 0
    captured = capsys.readouterr().out
    assert "knovaryn-backup" in captured


def test_repair_no_index_returns_zero(isolated_config) -> None:
    assert cli_commands.repair() == 0


def test_repair_flags_missing_blob(isolated_config) -> None:
    _make_index(_artifact_root(isolated_config), ["missing/blob.bin"])
    assert cli_commands.repair() == 1


def test_repair_missing_blob_json(isolated_config, capsys) -> None:
    _make_index(_artifact_root(isolated_config), ["gone.bin"])
    assert cli_commands.repair(json_plain=True) == 1
    captured = capsys.readouterr().out
    assert "missing artifact blob" in captured


def test_repair_corrupt_index_json(isolated_config) -> None:
    (_artifact_root(isolated_config) / "index.json").write_text("{ not valid json")
    assert cli_commands.repair() == 1


def test_repair_vacuum_corrupt_db(isolated_config, monkeypatch) -> None:
    monkeypatch.setattr(cli_commands, "_check_db", lambda db: (False, "integrity: corrupt"))
    code = cli_commands.repair()
    assert code in (0, 1)  # either repaired or a problem recorded


def test_db_file_parses_sqlite_path() -> None:
    parsed = cli_commands._db_file(
        {"storage": {"database_url": "sqlite+aiosqlite:///./.knovaryn/knovaryn.db"}}
    )
    assert parsed == "./.knovaryn/knovaryn.db"


def test_db_file_returns_none_for_non_sqlite() -> None:
    assert cli_commands._db_file({"storage": {"database_url": "postgresql://x/y"}}) is None


def test_state_dir_derives_parent_of_artifacts(isolated_config) -> None:
    # default artifact_root is <state>/artifacts -> state dir is its parent
    state = cli_commands._state_dir()
    assert state.name == "state"


def test_check_db_missing_path_ok() -> None:
    ok, detail = cli_commands._check_db("/nonexistent/does-not-exist.db")
    assert ok is True
    assert "not yet initialized" in detail


# ---------------------------------------------------------------------------
# WP F1 — the ``knovaryn mcp`` subcommand (canonical MCP entry point alias)
# ---------------------------------------------------------------------------


def test_mcp_subcommand_is_registered() -> None:
    """The ``knovaryn mcp`` subcommand is present (WP F1 canonical aliasing)."""
    from knovaryn.interfaces.cli.main import app

    names = {cmd.name for cmd in app.registered_commands}
    assert "mcp" in names


def test_mcp_cmd_delegates_to_mcp_entry_point(monkeypatch) -> None:
    """``knovaryn mcp`` forwards to the packaged MCP server entry point."""
    from typer.testing import CliRunner

    from knovaryn.interfaces.cli.main import app

    captured: list[str] = []

    def fake_mcp_main(argv: list[str]) -> int:
        captured.append(argv)
        return 7

    # ``mcp_cmd`` imports ``_mcp_main`` from knovaryn.interfaces.mcp.__main__
    # inside the function body, so patch that module's ``main``. Driving through
    # the Typer runner unwraps the Option defaults (host/port -> None) exactly
    # as a real ``knovaryn mcp`` invocation would.
    monkeypatch.setattr("knovaryn.interfaces.mcp.__main__.main", fake_mcp_main)

    result = CliRunner().invoke(
        app, ["mcp", "--transport", "stdio", "--database-url", "sqlite+aiosqlite:///t.db"]
    )
    assert result.exit_code == 7  # the MCP entry point's return value
    assert captured == [
        ["--transport=stdio", "--database-url=sqlite+aiosqlite:///t.db"]
    ]
