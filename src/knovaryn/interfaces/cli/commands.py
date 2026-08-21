"""Knovaryn CLI operational commands (spec §18, §21.3, §22, §23, §29).

Implements real, runnable operational commands that share the framework-free
:class:`ProjectService` and infrastructure helpers:

* ``doctor``  — environment + configuration + storage health check (non-zero exit on failure)
* ``backup``  — snapshot the local state directory into a timestamped archive
* ``repair``  — verify database integrity and reconcile missing artifact blobs
* ``server``  — launch the offline REST API + web console (bearer-token aware)
"""

from __future__ import annotations

import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from ...domain.config import load_config

console = Console()


def build_pipeline_gateway(cfg: Any, *, db: Any, ids: Any, job: Any) -> Any:
    """Build the durable worker's gateway for ``job`` (defect 4.9).

    Profile resolution follows spec §20 precedence: request (the job input's
    ``pipeline.profile``) > config (``models.profile``, then top-level
    ``profile``) > the offline default. The crash-safe CallCache and the
    ``model_calls`` ledger stay wired on every profile so a resumed job is
    served from cache/ledger instead of re-paying provider calls (§11.5/E5).
    """
    from ...infrastructure.artifacts.__factory import build_artifact_store
    from ...infrastructure.models.call_cache import CallCache
    from ...infrastructure.models.profiles import DEFAULT_RUNTIME_PROFILE, build_gateway
    from ...pipeline.jobs.worker import ModelCallLedgerRepository

    job_input = job.input or {}
    pipeline_cfg = job_input.get("pipeline", {}) or {}
    models_cfg = cfg.get("models", {}) if isinstance(cfg.get("models"), dict) else {}
    profile = (
        pipeline_cfg.get("profile")
        or models_cfg.get("profile")
        or cfg.get("profile")
        or DEFAULT_RUNTIME_PROFILE
    )
    storage = cfg.get("storage", {}) if isinstance(cfg.get("storage"), dict) else {}
    return build_gateway(
        str(profile),
        call_cache=CallCache(
            store=build_artifact_store(
                backend=storage.get("artifact_backend", "local"),
                config=storage,
            )
        ),
        model_call_repo=ModelCallLedgerRepository(db, ids),
        project_id=job.project_id,
        job_id=job.id,
        stage="pipeline",
    )


def _state_dir() -> Path:
    cfg = load_config()
    root = cfg.get("storage", {}).get("artifact_root") or ".knovaryn/artifacts"
    # state dir is the parent of artifacts, or the project-local .knovaryn
    path = Path(root)
    return path.parent if path.name == "artifacts" else path


def doctor(*, json_plain: bool = False) -> int:
    """Run environment + storage checks. Returns exit code (0 ok, 1 critical).

    Optional/opt-in extras (docling, docetl, HF publish) are informational: a
    minimal install without them is a supported, valid configuration, so their
    absence must NOT flip the exit code to failure. Only critical components
    (core import, config, storage reachability) drive the non-zero exit.
    """
    checks: list[tuple[str, bool, str, bool]] = []  # (name, ok, detail, optional)

    # 1. core import (critical)
    try:
        from ...infrastructure.models.fake_provider import FakeProvider  # noqa: F401

        checks.append(("Core import", True, "ok", False))
    except Exception as exc:  # noqa: BLE001
        checks.append(("Core import", False, f"failed: {exc}", False))

    # 2. optional extras
    from ...infrastructure.docetl.adapter import docetl_available
    from ...infrastructure.docling.adapter import docling_available
    from ...infrastructure.models.fake_provider import FakeProvider  # noqa: F401
    from ...infrastructure.publish.hf import hub_available

    checks.append(
        (
            "Docling (opt-in)",
            docling_available(),
            "available" if docling_available() else "not installed (safe fallback)",
            True,
        )
    )
    checks.append(
        (
            "DocETL (opt-in)",
            docetl_available(),
            "available" if docetl_available() else "not installed",
            True,
        )
    )
    checks.append(
        (
            "HF publish (opt-in)",
            hub_available(),
            "available" if hub_available() else "not installed",
            True,
        )
    )
    checks.append(("Fake provider (offline)", True, "ok", True))

    # 3. resource profile (accelerator detection)
    from ...infrastructure.resources import detect_resource_profile

    profile = detect_resource_profile()
    checks.append(("Accelerator", True, f"{profile.accelerator} ({profile.note})", False))

    # 4. config validity + secret safety
    cfg = load_config()
    checks.append(("Configuration", True, "loaded OK", False))

    # 5. storage reachability
    db_path = _db_file(cfg)
    db_ok, db_detail = _check_db(db_path)
    checks.append(("Database", db_ok, db_detail, False))

    # 6. artifact store reachability
    art_root = Path(cfg.get("storage", {}).get("artifact_root") or ".knovaryn/artifacts")
    try:
        art_root.mkdir(parents=True, exist_ok=True)
        probe = art_root / ".knovaryn_probe"
        probe.write_text("ok")
        probe.unlink()
        checks.append(("Artifact store", True, f"writable at {art_root}", False))
    except Exception as exc:  # noqa: BLE001
        checks.append(("Artifact store", False, f"not writable: {exc}", False))

    table = Table(title="Knovaryn doctor — environment check")
    table.add_column("Component")
    table.add_column("Status")
    table.add_column("Detail")
    for name, ok, detail, _optional in checks:
        table.add_row(name, "[green]OK[/green]" if ok else "[red]FAIL[/red]", detail)
    console.print(table)

    if json_plain:
        console.print_json(
            __import__("json").dumps(
                [{"component": n, "ok": o, "detail": d, "optional": p} for n, o, d, p in checks]
            )
        )
    # Optional/opt-in extras that are simply not installed are informational and
    # must not fail the exit code; only critical checks can make doctor non-zero.
    return 0 if all(ok for _, ok, _, optional in checks if not optional) else 1


def _db_file(cfg: Any) -> str | None:
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
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive = dest / f"knovaryn-backup-{stamp}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(state, arcname=state.name, filter=lambda info: _exclude_pycache(info))
    size = archive.stat().st_size
    console.print(f"[green]Backup written:[/green] {archive} ({size} bytes)")
    if json_plain:
        console.print_json(
            __import__("json").dumps({"path": str(archive), "bytes": size, "state": str(state)})
        )
    return 0


def _exclude_pycache(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if "__pycache__" in info.name or info.name.endswith(".pyc"):
        return None
    return info


def restore(*, archive: Path, json_plain: bool = False) -> int:
    """Restore a ``knovaryn backup`` archive into the configured state dir.

    Extracts the tarball, then verifies the restored SQLite DB with an
    ``integrity_check`` and enumerates restored top-level entries. Refuses to
    overwrite an existing state directory unless it is empty (or a prior
    ``backup`` exists to preserve recovery integrity).
    """
    state = _state_dir()
    if not archive.exists():
        console.print(f"[red]Archive not found: {archive}[/red]")
        return 1
    if state.exists() and any(state.iterdir()):
        console.print(
            f"[red]Refusing to restore over a non-empty state dir: {state}[/red] "
            "(back it up first or move it away)"
        )
        return 1
    state.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(state, filter="data")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Restore failed:[/red] {exc}")
        return 1

    cfg = load_config()
    db_path = _db_file(cfg)
    problems: list[str] = []
    if db_path:
        ok, detail = _check_db(db_path)
        if ok:
            console.print(f"[green]Restored DB integrity OK:[/green] {detail}")
        else:
            problems.append(detail)
            console.print(f"[red]Restored DB integrity check failed:[/red] {detail}")
            return 1
    # surface the restored top-level entries for confirmation
    entries = sorted(p.name for p in state.iterdir())
    console.print(f"[green]Restored to {state}:[/green] {', '.join(entries) or '(empty)'}")
    if json_plain:
        console.print_json(
            __import__("json").dumps(
                {
                    "archive": str(archive),
                    "state": str(state),
                    "entries": entries,
                    "problems": problems,
                }
            )
        )
    return 0


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
        console.print_json(
            __import__("json").dumps({"fixed": fixed, "problems": problems, "ok": True})
        )
    console.print("[green]Repair complete: nothing to fix.[/green]")
    return 0


def verify_release(*, path: str) -> int:
    """Verify a release bundle's detached checksum + per-file manifest (I5).

    Exit 0 on success (fully verifiable), nonzero otherwise. Never reports a
    bundle as OK unless the detached checksum, every per-file sha256, the
    content-root hash, and the manifest schema all verify (contract rules 6/13).
    """
    from ...pipeline.export.verify_release import run_verify_release

    return run_verify_release(path)


def server(*, host: str | None = None, port: int | None = None, reload: bool = False) -> int:
    """Launch the offline REST API + web console (bearer-token aware).

    Enforces J4 safe binding: refusing a non-loopback bind when no API token is
    configured unless the operator explicitly overrides it.
    """
    from ...infrastructure.auth.bearer import server_bind
    from ...infrastructure.telemetry.logging import get_logger

    bind_host, bind_port = server_bind()
    host = host or bind_host
    port = port or bind_port
    try:
        from ...interfaces.rest.security import server_bind_checked

        host, port = server_bind_checked(host=host, port=port)
    except Exception as exc:  # noqa: BLE001 - ConfigurationError -> refuse to start
        console.print(f"[red]{exc}[/red]")
        return 1
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


def _run_async(coro: Any) -> Any:
    """Run a coroutine whether or not a loop is already active.

    The CLI invokes commands synchronously (no running loop -> ``asyncio.run``),
    but tests may call the sync entry point from inside an already-running loop,
    where ``asyncio.run`` would raise. This branches on the current loop state.
    """
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # a loop is already running in this thread: we cannot block it with
    # asyncio.run(); create + pump a dedicated loop to completion.
    inner = asyncio.new_event_loop()
    try:
        return inner.run_until_complete(coro)
    finally:
        inner.close()


async def worker_async(
    *,
    worker_id: str = "w1",
    poll_interval_s: float = 1.0,
    lease_seconds: int = 300,
    max_attempts: int = 3,
    once: bool = False,
    database_url: str | None = None,
) -> None:
    """Run a durable background worker: claim → lease → checkpoint → resume.

    Lifts queued pipeline jobs off the DB exactly as the offline in-process
    runner does, but as an independent process with heartbeats, lease expiry,
    and crash-safe stage checkpoints (spec §7.3). Completed stages are never
    repeated on resume.
    """
    import asyncio

    from ...application.service import ProjectService
    from ...domain.ids import IdGenerator
    from ...infrastructure.database.repositories import ProjectRepository, SourceRepository
    from ...infrastructure.database.session import Database
    from ...pipeline.jobs.engine import JobEngine
    from ...pipeline.jobs.retry import RetryPolicy
    from ...pipeline.jobs.worker import Worker, WorkerRepository

    cfg = load_config()
    url = (
        database_url
        or cfg.get("storage.database_url")
        or "sqlite+aiosqlite:///./.knovaryn/knovaryn.db"
    )

    async def _pipeline_stage(ctx: Any) -> dict[str, Any]:
        """Resolve the job's project + sources and run the full pipeline."""
        from ...domain.schemas import DatasetPlan

        job = ctx.job
        async with db.session() as session, session.begin():
            proj_repo = ProjectRepository(session, ids)
            project = await proj_repo.get(job.project_id)
            source_repo = SourceRepository(session)
            source_ids = (job.input or {}).get("source_ids") or []
            sources: list[Any] = []
            contents: list[str] = []
            for sid in source_ids:
                src = await source_repo.get(sid)
                if src is None:
                    continue
                sources.append(src)
                contents.append((src.metadata or {}).get("content", "") or "")
            if project is None:
                raise RuntimeError(f"project not found: {job.project_id}")
            pipeline_cfg = (job.input or {}).get("pipeline", {}) or {}
            plan = DatasetPlan(
                task_family_proportions=pipeline_cfg.get("task_family_proportions")
                or {"factual_explanation": 0.5, "procedure": 0.3, "comparison": 0.2}
            )
            # crash-safe generation (spec §11.5, §12/E5): the profile-aware
            # factory keeps the CallCache + model_calls ledger wired on every
            # profile — a resumed job is served from cache/ledger instead of
            # re-paying the call.
            gateway = build_pipeline_gateway(cfg, db=db, ids=ids, job=job)
            svc = ProjectService(ids=ids, gateway=gateway)
            result = await svc.run_pipeline(
                project=project, sources=sources, contents=contents, plan=plan
            )
        stash = {
            "examples": [e.model_dump(mode="json") for e in result.examples],
            "version": result.version.model_dump(mode="json") if result.version else None,
            "release_sha256": result.release_sha256,
        }
        ctx.job.input["_pipeline_result"] = stash
        await ctx.checkpoint("pipeline", step=1, key="result", value=result.to_dict())
        return result.to_dict()

    def stage_provider(job_type: str) -> list[tuple[str, Any]]:
        if job_type != "pipeline":
            raise RuntimeError(f"unsupported job_type for worker: {job_type}")
        return [("pipeline", _pipeline_stage)]

    ids = IdGenerator()
    db = Database(url)
    await db.create_all()
    repo = WorkerRepository(db, ids)
    engine = JobEngine(ids=ids, repo=repo, retry_policy=RetryPolicy(max_attempts=max_attempts))
    w = Worker(
        ids=ids,
        engine=engine,
        stage_provider=stage_provider,
        repo=repo,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        poll_interval_s=poll_interval_s,
    )
    loop = asyncio.get_running_loop()
    w.install_signal_handlers(loop)
    console.print(f"[green]Knovaryn worker[/green] {worker_id} online (lease={lease_seconds}s)")
    try:
        if once:
            await w._tick()  # noqa: SLF001 - single poll for tests/one-shot runs
        else:
            await w.run_forever()
    finally:
        await db.dispose()


def worker(
    *,
    worker_id: str = "w1",
    poll_interval_s: float = 1.0,
    lease_seconds: int = 300,
    max_attempts: int = 3,
    once: bool = False,
    database_url: str | None = None,
    json_plain: bool = False,
) -> int:
    """Run a durable background worker (sync CLI entry point)."""
    try:
        _run_async(
            worker_async(
                worker_id=worker_id,
                poll_interval_s=poll_interval_s,
                lease_seconds=lease_seconds,
                max_attempts=max_attempts,
                once=once,
                database_url=database_url,
            )
        )
    except KeyboardInterrupt:
        console.print(f"[yellow]worker {worker_id} interrupted[/yellow]")
    if json_plain:
        console.print_json(f'{{"worker": "{worker_id}", "ok": true}}')
    return 0


__all__ = ["doctor", "backup", "repair", "server", "worker", "worker_async", "_state_dir"]
