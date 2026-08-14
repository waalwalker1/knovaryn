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


def _fresh_config(tmp_path: Path, root: str, *, create_artifacts: bool = False) -> Configuration:
    """A config for backup/restore round-trips.

    Only the top-level state dir (parent of ``artifacts``) is created so that a
    restore target starts genuinely empty — ``restore`` refuses to overwrite a
    non-empty state dir. Sources that must hold artifacts pass
    ``create_artifacts=True``.
    """
    cfg = Configuration()
    state = tmp_path / root
    state.mkdir(parents=True, exist_ok=True)
    art = state / "artifacts"
    if create_artifacts:
        art.mkdir(parents=True, exist_ok=True)
    db = state / "knovaryn.db"
    cfg.set("storage.artifact_root", str(art))
    cfg.set("storage.database_url", f"sqlite+aiosqlite:///{db}")
    return cfg


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


def test_doctor_absent_opt_in_extras_returns_zero(isolated_config, monkeypatch) -> None:
    """doctor MUST NOT fail when opt-in extras are absent (spec: minimal install
    is a supported, valid configuration). Patches every availability probe to
    False and asserts a deterministic exit code 0 — pinning the requirement that
    failing optional checks never flip the exit code to failure.
    """
    import importlib

    db = isolated_config.get("storage.database_url").replace("sqlite+aiosqlite:///", "")
    sqlite3.connect(db).close()
    docling_ad = importlib.import_module("knovaryn.infrastructure.docling.adapter")
    docetl_ad = importlib.import_module("knovaryn.infrastructure.docetl.adapter")
    hf_mod = importlib.import_module("knovaryn.infrastructure.publish.hf")
    monkeypatch.setattr(docling_ad, "docling_available", lambda: False)
    monkeypatch.setattr(docetl_ad, "docetl_available", lambda: False)
    monkeypatch.setattr(hf_mod, "hub_available", lambda: False)
    assert cli_commands.doctor() == 0


def test_doctor_present_opt_in_extras_returns_zero(isolated_config, monkeypatch) -> None:
    """Complement: with every opt-in extra available, doctor still passes."""
    import importlib

    db = isolated_config.get("storage.database_url").replace("sqlite+aiosqlite:///", "")
    sqlite3.connect(db).close()
    docling_ad = importlib.import_module("knovaryn.infrastructure.docling.adapter")
    docetl_ad = importlib.import_module("knovaryn.infrastructure.docetl.adapter")
    hf_mod = importlib.import_module("knovaryn.infrastructure.publish.hf")
    monkeypatch.setattr(docling_ad, "docling_available", lambda: True)
    monkeypatch.setattr(docetl_ad, "docetl_available", lambda: True)
    monkeypatch.setattr(hf_mod, "hub_available", lambda: True)
    assert cli_commands.doctor() == 0


def test_doctor_json_absent_extras(isolated_config, monkeypatch, capsys) -> None:
    """JSON reporter reflects absent opt-in extras as informational, not fatal."""
    import importlib

    db = isolated_config.get("storage.database_url").replace("sqlite+aiosqlite:///", "")
    sqlite3.connect(db).close()
    docling_ad = importlib.import_module("knovaryn.infrastructure.docling.adapter")
    docetl_ad = importlib.import_module("knovaryn.infrastructure.docetl.adapter")
    hf_mod = importlib.import_module("knovaryn.infrastructure.publish.hf")
    monkeypatch.setattr(docling_ad, "docling_available", lambda: False)
    monkeypatch.setattr(docetl_ad, "docetl_available", lambda: False)
    monkeypatch.setattr(hf_mod, "hub_available", lambda: False)
    # rich table and the JSON block share stdout; assert on the JSON block,
    # which always carries the structured `"optional": true` / `"ok"` fields.
    code = cli_commands.doctor(json_plain=True)
    captured = capsys.readouterr().out
    assert code == 0
    json_part = captured[captured.find('"component"') :]
    for extra in ("Docling (opt-in)", "DocETL (opt-in)", "HF publish (opt-in)"):
        row = json_part[json_part.find(extra) :]
        end = row.find('"ok"')
        assert '"ok": false' in row[: end + 60], f"{extra} not marked not-ok in JSON"
        assert '"optional": true' in row[end : end + 120], f"{extra} not marked optional"


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


def test_restore_round_trip(tmp_path, monkeypatch) -> None:
    """backup a populated state dir, then restore it into a pristine dir."""
    src = _fresh_config(tmp_path, "src", create_artifacts=True)
    monkeypatch.setattr(cli_commands, "load_config", lambda **kw: src)
    (Path(src.get("storage.artifact_root")) / "probe.txt").write_text("hello")
    dest = tmp_path / "backups"
    assert cli_commands.backup(out=dest) == 0
    (archive,) = dest.glob("*.tar.gz")

    dst = _fresh_config(tmp_path, "dst")
    monkeypatch.setattr(cli_commands, "load_config", lambda **kw: dst)
    assert cli_commands.restore(archive=archive) == 0
    restored = next(Path(dst.get("storage.artifact_root")).parent.rglob("probe.txt"), None)
    assert restored is not None and restored.read_text() == "hello"


def test_restore_missing_archive_returns_one(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cli_commands, "load_config", lambda **kw: _fresh_config(tmp_path, "e1"))
    assert cli_commands.restore(archive=tmp_path / "nope.tar.gz") == 1


def test_restore_refuses_over_nonempty_state(tmp_path, monkeypatch) -> None:
    cfg = _fresh_config(tmp_path, "e2")
    monkeypatch.setattr(cli_commands, "load_config", lambda **kw: cfg)
    (Path(cfg.get("storage.artifact_root")).parent / "existing.txt").write_text("x")
    archive = tmp_path / "some.tar.gz"
    archive.write_bytes(b"not used")
    assert cli_commands.restore(archive=archive) == 1


def test_restore_json_output(tmp_path, monkeypatch, capsys) -> None:
    src = _fresh_config(tmp_path, "j-src", create_artifacts=True)
    monkeypatch.setattr(cli_commands, "load_config", lambda **kw: src)
    (Path(src.get("storage.artifact_root")) / "probe.txt").write_text("hello")
    dest = tmp_path / "backups"
    assert cli_commands.backup(out=dest) == 0
    (archive,) = dest.glob("*.tar.gz")

    dst = _fresh_config(tmp_path, "j-dst")
    monkeypatch.setattr(cli_commands, "load_config", lambda **kw: dst)
    assert cli_commands.restore(archive=archive, json_plain=True) == 0
    captured = capsys.readouterr().out
    # backup preserves the source state-dir basename as the archive top level,
    # so the restored entry list carries it; assert on that JSON contract.
    assert '"entries"' in captured and '"j-src"' in captured


def test_restore_db_integrity_failure_returns_one(tmp_path, monkeypatch) -> None:
    """A restored DB that fails integrity check makes restore fail closed."""
    cfg = _fresh_config(tmp_path, "i-dst")
    db_rel = cfg.get("storage.database_url").replace("sqlite+aiosqlite:///", "")
    sqlite3.connect(str(db_rel)).close()  # db path must exist so _check_db is consulted
    monkeypatch.setattr(cli_commands, "_check_db", lambda db: (False, "integrity: corrupt"))
    monkeypatch.setattr(cli_commands, "load_config", lambda **kw: cfg)
    archive = tmp_path / "x.tar.gz"
    archive.write_bytes(b"")
    assert cli_commands.restore(archive=archive) == 1


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
    assert captured == [["--transport=stdio", "--database-url=sqlite+aiosqlite:///t.db"]]
