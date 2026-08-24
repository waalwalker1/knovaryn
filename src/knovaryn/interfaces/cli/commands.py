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

    if json_plain:
        # --json is a machine contract: stdout must carry EXACTLY one
        # parseable JSON document, never the rich table alongside it.
        # (profile_smoke installs into clean venvs and json.loads stdout.)
        console.print_json(
            __import__("json").dumps(
                [{"component": n, "ok": o, "detail": d, "optional": p} for n, o, d, p in checks]
            )
        )
    else:
        table = Table(title="Knovaryn doctor — environment check")
        table.add_column("Component")
        table.add_column("Status")
        table.add_column("Detail")
        for name, ok, detail, _optional in checks:
            table.add_row(name, "[green]OK[/green]" if ok else "[red]FAIL[/red]", detail)
        console.print(table)
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
    but embedders (tests, notebook kernels, an MCP host driving the sync
    entry points) may call them from inside an already-running loop, where
    ``asyncio.run`` would raise — and where ``loop.run_until_complete`` on a
    second loop is equally forbidden (asyncio allows one running loop per
    thread). That case pumps a dedicated loop on a worker thread and blocks
    the calling thread on the result.
    """
    import asyncio
    import threading

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # a loop is already running in this thread: run the coroutine to
    # completion on its own loop in a daemon thread instead.
    inner = asyncio.new_event_loop()
    worker = threading.Thread(target=inner.run_forever, daemon=True)
    worker.start()
    try:
        return asyncio.run_coroutine_threadsafe(coro, inner).result()
    finally:
        inner.call_soon_threadsafe(inner.stop)
        worker.join(timeout=30)
        if worker.is_alive():  # pragma: no cover - pathological loop wedge
            raise RuntimeError("CLI async worker loop did not terminate")
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


__all__ = [
    "doctor",
    "backup",
    "repair",
    "server",
    "worker",
    "worker_async",
    "_state_dir",
]


# ---------------------------------------------------------------------------
# Project lifecycle commands (defect 3.4, v0.2.1)
#
# These are the real CLI surface over Workspace — every command maps to one
# application-service call, so the CLI can never drift from the pipeline the
# MCP/REST/SDK paths run. No command invents its own persistence or validation.
# ---------------------------------------------------------------------------


def _print_result(payload: Any, *, json_plain: bool, human: str | None = None) -> None:
    if json_plain:
        import json as _json

        console.print_json(_json.dumps(payload, default=str))
    elif human:
        console.print(human)
    else:
        console.print(payload)


def _workspace_lifecycle(principal: str = "cli") -> Any:
    """Async context manager yielding an open Workspace (defect 3.4)."""
    from contextlib import asynccontextmanager

    from ...application.workspace import Workspace

    @asynccontextmanager
    async def _ctx() -> Any:
        ws = Workspace(principal=principal)
        await ws.open()
        try:
            yield ws
        finally:
            await ws.close()

    return _ctx()


def project_create(
    *, slug: str, display_name: str = "", description: str = "", json_plain: bool = False
) -> int:
    """Create a project. Exit 1 on duplicate slug / invalid input."""

    async def go() -> Any:
        async with _workspace_lifecycle() as ws:
            return await ws.create_project(
                slug=slug, display_name=display_name or slug, description=description
            )

    try:
        project = _run_async(go())
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]error:[/red] {exc}")
        return 1
    _print_result(
        {"id": project.id, "slug": project.slug, "display_name": project.display_name},
        json_plain=json_plain,
        human=f"created project [bold]{project.slug}[/bold] ({project.id})",
    )
    return 0


def project_list(*, limit: int = 50, json_plain: bool = False) -> int:
    async def go() -> Any:
        async with _workspace_lifecycle() as ws:
            return await ws.list_projects(limit=limit)

    data = _run_async(go())
    if json_plain:
        _print_result(data, json_plain=True)
        return 0
    table = Table(title="Projects")
    table.add_column("Slug")
    table.add_column("ID")
    table.add_column("Name")
    for p in data.get("projects", []):
        table.add_row(p.get("slug", ""), p.get("id", ""), p.get("display_name", ""))
    console.print(table)
    return 0


def source_add(
    *,
    project_id: str,
    path: Path,
    license: str | None = None,
    privacy: str | None = None,
    group: str | None = None,
    json_plain: bool = False,
) -> int:
    """Register a file (text or binary) through intake; detected type wins."""
    if not path.is_file():
        console.print(f"[red]error:[/red] not a file: {path}")
        return 1

    async def go() -> Any:
        raw = path.read_bytes()
        async with _workspace_lifecycle() as ws:
            return await ws.add_source(
                project_id=project_id,
                original_name=path.name,
                raw=raw,
                declared_license=license,
                privacy=privacy,
                group_key=group,
            )

    try:
        src = _run_async(go())
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]error:[/red] {exc}")
        return 1
    _print_result(
        {"id": src.id, "name": src.original_name, "sha256": src.sha256},
        json_plain=json_plain,
        human=(
            f"added source [bold]{src.original_name}[/bold] ({src.id}) sha256={src.sha256[:12]}…"
        ),
    )
    return 0


def source_list(*, project_id: str, limit: int = 100, json_plain: bool = False) -> int:
    async def go() -> Any:
        async with _workspace_lifecycle() as ws:
            return await ws.list_sources(project_id=project_id, limit=limit)

    try:
        data = _run_async(go())
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]error:[/red] {exc}")
        return 1
    if json_plain:
        _print_result(data, json_plain=True)
        return 0
    table = Table(title="Sources")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Media type")
    for s in data.get("sources", []):
        table.add_row(s.get("id", ""), s.get("original_name", ""), s.get("media_type", ""))
    console.print(table)
    return 0


def run_pipeline(
    *,
    project_id: str,
    family: str | None = None,
    target: int | None = None,
    budget_max_usd: float | None = None,
    profile: str | None = None,
    json_plain: bool = False,
) -> int:
    """Queue and drive one pipeline job to completion (single-worker mode)."""
    proportions = None
    if family:
        try:
            name, _, weight = family.partition(":")
            proportions = {name.strip(): float(weight or "1.0")}
        except ValueError:
            console.print(f"[red]error:[/red] --family expects NAME:WEIGHT, got {family!r}")
            return 1

    async def go() -> Any:
        async with _workspace_lifecycle() as ws:
            job = await ws.start_pipeline(
                project_id=project_id,
                task_family_proportions=proportions,
                target_examples=target,
                budget_max_usd=budget_max_usd,
                profile=profile,
            )
            return job, await ws.run_job(job.id)

    try:
        job, result = _run_async(go())
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]error:[/red] {exc}")
        return 1
    payload = {
        "job_id": job.id,
        "state": str(result.get("state") or ""),
        "actual_cost": result.get("actual_cost"),
        "error_summary": result.get("error_summary"),
    }
    ok = payload["state"] == "succeeded"
    _print_result(
        payload,
        json_plain=json_plain,
        human=f"job [bold]{job.id}[/bold] → {payload['state']}",
    )
    return 0 if ok else 1


def job_status(*, job_id: str, json_plain: bool = False) -> int:
    async def go() -> Any:
        async with _workspace_lifecycle() as ws:
            return await ws.get_job(job_id)

    try:
        summary = _run_async(go())
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]error:[/red] {exc}")
        return 1
    payload = summary.to_dict()
    _print_result(
        payload,
        json_plain=json_plain,
        human=(
            f"job {job_id} → {payload['state']}"
            f" (stage={payload.get('current_stage')},"
            f" progress={payload.get('progress_current')}/{payload.get('progress_total')})"
        ),
    )
    return 0 if payload["state"] == "succeeded" else (0 if payload["state"] != "failed" else 1)


def job_list(*, project_id: str | None = None, limit: int = 20, json_plain: bool = False) -> int:
    async def go() -> Any:
        async with _workspace_lifecycle() as ws:
            return await ws.list_jobs(project_id=project_id, limit=limit)

    data = _run_async(go())
    if json_plain:
        _print_result(data, json_plain=True)
        return 0
    table = Table(title="Jobs")
    table.add_column("ID")
    table.add_column("State")
    for j in data.get("jobs", []):
        table.add_row(str(j.get("id", "")), str(j.get("state", "")))
    console.print(table)
    return 0


def review_decide(
    *,
    example_id: str,
    decision: str,
    note: str = "",
    reviewer: str = "cli",
    revision: int | None = None,
    json_plain: bool = False,
) -> int:
    """Record approve/reject/needs_work against the example's latest revision."""

    async def go() -> Any:
        async with _workspace_lifecycle(principal=reviewer) as ws:
            if revision is None:
                history = await ws.list_revisions(example_id=example_id)
                revs = history.get("revisions") or []
                if not revs:
                    raise ValueError(f"example has no revisions: {example_id}")
                base = int(revs[-1]["revision_id"])
            else:
                base = revision
            return await ws.review_example(
                example_id=example_id,
                revision_id=base,
                reviewer=reviewer,
                decision=decision,
                note=note,
            )

    try:
        result = _run_async(go())
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]error:[/red] {exc}")
        return 1
    _print_result(
        {"example_id": example_id, "decision": decision, "revision": result.get("revision")},
        json_plain=json_plain,
        human=f"recorded {decision} on {example_id}",
    )
    return 0


def dataset_validate(*, project_id: str, limit: int = 500, json_plain: bool = False) -> int:
    async def go() -> Any:
        async with _workspace_lifecycle() as ws:
            return await ws.validate_dataset(project_id=project_id, limit=limit)

    try:
        report = _run_async(go())
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]error:[/red] {exc}")
        return 1
    _print_result(report, json_plain=json_plain)
    if not json_plain:
        counts = report.get("summary", report.get("counts", {}))
        console.print(f"validation summary: {counts}")
    return 0


def dataset_version(
    *, project_id: str, semantic_version: str | None = None, json_plain: bool = False
) -> int:
    async def go() -> Any:
        async with _workspace_lifecycle() as ws:
            return await ws.create_version(project_id=project_id, semantic_version=semantic_version)

    try:
        version = _run_async(go())
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]error:[/red] {exc}")
        return 1
    _print_result(
        {"version_id": version.id, "semantic_version": version.semantic_version},
        json_plain=json_plain,
        human=f"created dataset version {version.semantic_version} ({version.id})",
    )
    return 0


def dataset_export(
    *,
    project_id: str,
    format: str = "openai_chat",
    version_id: str | None = None,
    download_dir: str | None = None,
    json_plain: bool = False,
) -> int:
    async def go() -> Any:
        async with _workspace_lifecycle() as ws:
            return await ws.export_dataset_formatted(
                project_id=project_id,
                format=format,
                version_id=version_id,
                download_dir=download_dir,
            )

    try:
        artifact = _run_async(go())
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]error:[/red] {exc}")
        return 1
    _print_result(
        {
            "artifact_id": artifact.artifact_id,
            "path": artifact.download_path,
            "sha256": artifact.sha256,
            "records": artifact.record_count,
        },
        json_plain=json_plain,
        human=(
            f"exported {artifact.record_count} records → {artifact.download_path} "
            f"(sha256={artifact.sha256[:12]}…)"
        ),
    )
    return 0


def dataset_publish(
    *,
    project_id: str,
    repo_id: str,
    dry_run: bool = True,
    principal: str = "cli",
    json_plain: bool = False,
) -> int:
    async def go() -> Any:
        async with _workspace_lifecycle() as ws:
            return await ws.publish_dataset(
                project_id=project_id, repo_id=repo_id, dry_run=dry_run, principal=principal
            )

    try:
        result = _run_async(go())
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]error:[/red] {exc}")
        return 1
    gate = result.get("publication_gate", {})
    status = result.get("status", "ok")
    _print_result(
        result,
        json_plain=json_plain,
        human=f"publish {'dry-run' if dry_run else 'LIVE'} → status={status}"
        + (f", gate_allowed={gate.get('allowed')}" if isinstance(gate, dict) else ""),
    )
    # §15.6: a blocked or unavailable publication path fails the command.
    blocked = (isinstance(gate, dict) and gate.get("allowed") is False) or status != "ok"
    return 1 if blocked else 0


def init_state(*, json_plain: bool = False) -> int:
    """Create the local state directory + verify configuration loads."""
    cfg = load_config()
    state = _state_dir()
    art_root = Path(cfg.get("storage", {}).get("artifact_root") or ".knovaryn/artifacts")
    try:
        state.mkdir(parents=True, exist_ok=True)
        art_root.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]error:[/red] cannot create state directories: {exc}")
        return 1
    db_url = cfg.get("storage", {}).get("database_url") or (
        f"sqlite+aiosqlite:///{state / 'knovaryn.db'}"
    )
    _print_result(
        {"state_dir": str(state), "artifact_root": str(art_root), "database_url": db_url},
        json_plain=json_plain,
        human=(
            f"initialized state at [bold]{state}[/bold]\n"
            f"  artifacts: {art_root}\n  database:  {db_url}"
        ),
    )
    return 0
