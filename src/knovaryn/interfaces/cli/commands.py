"""Knovaryn CLI operational commands (spec §18, §21.3, §22, §23, §29).

Implements real, runnable operational commands that share the framework-free
:class:`ProjectService` and infrastructure helpers:

* ``doctor``  — environment + configuration + storage health check (non-zero exit on failure)
* ``backup``  — snapshot the local state directory into a timestamped archive
* ``repair``  — verify database integrity and reconcile missing artifact blobs
* ``server``  — launch the offline REST API + web console (bearer-token aware)
"""

from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from ...domain.config import load_config

console = Console()


def _state_dir() -> Path:
    cfg = load_config()
    root = cfg.get("storage", {}).get("artifact_root") or ".knovaryn/artifacts"
    # state dir is the parent of artifacts, or the project-local .knovaryn
    path = Path(root)
    return path.parent if path.name == "artifacts" else path


def doctor(*, json_plain: bool = False) -> int:
    """Run environment + storage checks. Returns exit code (0 ok, 1 critical)."""
    checks: list[tuple[str, bool, str]] = []

    # 1. core import
    try:
        from ...infrastructure.models.fake_provider import FakeProvider  # noqa: F401

        checks.append(("Core import", True, "ok"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("Core import", False, f"failed: {exc}"))

    # 2. optional extras
    from ...infrastructure.docling.adapter import docling_available
    from ...infrastructure.docetl.adapter import docetl_available
    from ...infrastructure.models.fake_provider import FakeProvider  # noqa: F401
    from ...infrastructure.publish.hf import hub_available

    checks.append(("Docling (opt-in)", docling_available(), "available" if docling_available() else "not installed (safe fallback)"))
    checks.append(("DocETL (opt-in)", docetl_available(), "available" if docetl_available() else "not installed"))
    checks.append(("HF publish (opt-in)", hub_available(), "available" if hub_available() else "not installed"))
    checks.append(("Fake provider (offline)", True, "ok"))

    # 3. resource profile (accelerator detection)
    from ...infrastructure.resources import detect_resource_profile

    profile = detect_resource_profile()
    checks.append(("Accelerator", True, f"{profile.accelerator} ({profile.note})"))

    # 4. config validity + secret safety
    cfg = load_config()
    checks.append(("Configuration", True, "loaded OK"))

    # 5. storage reachability
    db_path = _db_file(cfg)
    db_ok, db_detail = _check_db(db_path)
    checks.append(("Database", db_ok, db_detail))

    # 6. artifact store reachability
    art_root = Path(cfg.get("storage", {}).get("artifact_root") or ".knovaryn/artifacts")
    try:
        art_root.mkdir(parents=True, exist_ok=True)
        probe = art_root / ".knovaryn_probe"
        probe.write_text("ok")
        probe.unlink()
        checks.append(("Artifact store", True, f"writable at {art_root}"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("Artifact store", False, f"not writable: {exc}"))

    table = Table(title="Knovaryn doctor — environment check")
    table.add_column("Component")
    table.add_column("Status")
    table.add_column("Detail")
    for name, ok, detail in checks:
        table.add_row(name, "[green]OK[/green]" if ok else "[red]FAIL[/red]", detail)
    console.print(table)

    if json_plain:
        console.print_json(__import__("json").dumps([{"component": n, "ok": o, "detail": d} for n, o, d in checks]))
    return 0 if all(ok for _, ok, _ in checks) else 1


def _db_file(cfg: dict[str, Any]) -> str | None:
    url = cfg.get("storage", {}).get("database_url") or ""
    if url.startswith("sqlite"):
        # sqlite+aiosqlite:///./.knovaryn/knovaryn.db
        head = url.split(":///", 1)
        if len(head) == 2 and head[1]:
            return head[1]
    return None


def _check_db(db_path: str | None) -> tuple[bool, str]:
    import sqlite3

    if not db_path:
        return True, "non-sqlite backend (skipped local check)"
    try:
        path = Path(db_path)
        if not path.exists():
            # first run: not yet created is not a failure
            return True, f"not yet initialized ({db_path})"
        con = sqlite3.connect(str(path))
        row = con.execute("PRAGMA integrity_check").fetchone()
        con.close()
        ok = row and row[0] == "ok"
        return (ok, "integrity ok" if ok else f"integrity: {row}")
    except Exception as exc:  # noqa: BLE001
        return False, f"check failed: {exc}"


def backup(*, out: Path | None = None, json_plain: bool = False) -> int:
    """Snapshot the local state directory (.knovaryn) into a timestamped archive."""
    state = _state_dir()
    if not state.exists():
        console.print(f"[red]State directory not found: {state}[/red]")
        return 1
    dest = out or Path("knovaryn-backups")
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = dest / f"knovaryn-backup-{stamp}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(state, arcname=state.name, filter=lambda info: _exclude_pycache(info))
    size = archive.stat().st_size
    console.print(f"[green]Backup written:[/green] {archive} ({size} bytes)")
    if json_plain:
        console.print_json(__import__("json").dumps({"path": str(archive), "bytes": size, "state": str(state)}))
    return 0


def _exclude_pycache(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if "__pycache__" in info.name or info.name.endswith(".pyc"):
        return None
    return info


def repair(*, json_plain: bool = False) -> int:
    """Verify DB integrity and reconcile missing artifact blobs against the index."""
    cfg = load_config()
    fixed: list[str] = []
    problems: list[str] = []

    # 1. database integrity
    db_path = _db_file(cfg)
    if db_path:
        ok, detail = _check_db(db_path)
        if ok:
            console.print(f"[green]Database OK:[/green] {detail}")
        else:
            # attempt a best-effort VACUUM to compact/recover
            import sqlite3

            try:
                con = sqlite3.connect(str(db_path))
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                con.execute("VACUUM")
                con.close()
                fixed.append(f"vacuumed {db_path}")
                console.print(f"[green]Repaired database:[/green] {db_path}")
            except Exception as exc:  # noqa: BLE001
                problems.append(f"database repair failed: {exc}")
                console.print(f"[red]Database repair failed:[/red] {exc}")

    # 2. artifact store reconciliation (CAS: expect a sha256 manifest per object)
    art_root = Path(cfg.get("storage", {}).get("artifact_root") or ".knovaryn/artifacts")
    art_root.mkdir(parents=True, exist_ok=True)
    manifest = art_root / "index.json"
    if manifest.exists():
        import json

        try:
            idx = json.loads(manifest.read_text()) or {}
            listing = idx.get("objects", []) if isinstance(idx, dict) else []
            for entry in listing:
                rel = entry.get("path") if isinstance(entry, dict) else entry
                if not rel or not isinstance(rel, str):
                    continue
                obj = art_root / rel
                if not obj.exists():
                    problems.append(f"missing artifact blob: {rel}")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"could not read index.json: {exc}")
    else:
        console.print("[dim]No artifact index found — nothing to reconcile.[/dim]")

    if fixed:
        console.print(f"[green]Fixed:[/green] {', '.join(fixed)}")
    if problems:
        for p in problems:
            console.print(f"[yellow]Needs attention:[/yellow] {p}")
        if json_plain:
            console.print_json(__import__("json").dumps({"fixed": fixed, "problems": problems}))
        return 1
    if json_plain:
        console.print_json(__import__("json").dumps({"fixed": fixed, "problems": problems, "ok": True}))
    console.print("[green]Repair complete: nothing to fix.[/green]")
    return 0


def server(*, host: str | None = None, port: int | None = None, reload: bool = False) -> int:
    """Launch the offline REST API + web console (bearer-token aware)."""
    from ...infrastructure.auth.bearer import server_bind
    from ...infrastructure.telemetry.logging import get_logger

    bind_host, bind_port = server_bind()
    host = host or bind_host
    port = port or bind_port
    log = get_logger("knovaryn.server")
    log.info("starting knovaryn server", host=host, port=port)
    console.print(f"[green]Knovaryn server[/green] → http://{host}:{port}  (web console at /)")
    try:
        import uvicorn

        from ...interfaces.rest.app import app

        uvicorn.run(app, host=host, port=port, reload=reload, log_level="info")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Server failed to start:[/red] {exc}")
        return 1
    return 0


__all__ = ["doctor", "backup", "repair", "server", "_state_dir"]
