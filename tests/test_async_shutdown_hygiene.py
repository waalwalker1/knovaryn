"""Defect 3.2 (v0.2.1) — async shutdown hygiene regression tests.

The v0.2.0 release leaked aiosqlite worker threads whose op futures were
resolved after their event loop closed, surfacing as
``RuntimeError('Event loop is closed')`` collected by pytest at the NEXT
test's setup (flaky cross-test pollution), plus pydantic_settings'
``IncompleteFieldDefinitionWarning`` on every MCP server construction.

Root causes fixed for 0.2.1:
* pooled SQLite connections dangling until engine disposal → ``NullPool`` so
  every connection closes deterministically inside its session context;
* disposal itself abortable mid-flight by cancellation → shielded dispose;
* 1.x SDK ``Settings.lifespan`` unresolved forward ref → ``model_rebuild()``
  in the compat adapter.

These tests encode each signature so the class of failure cannot silently
return: repeated full MCP lifecycles against a real SQLite workspace, then
assertions that (a) no aiosqlite worker thread survives the lifecycles,
(b) no thread raises anything after the event loop has closed, and (c) server
construction emits no incomplete-field warning.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
import warnings as _warnings
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.mcp]


def _worker_thread_names() -> set[str]:
    return {
        t.name for t in threading.enumerate() if "_connection_worker" in t.name
    }


async def _run_mcp_lifecycles(db_url: str, cycles: int) -> None:
    """Run ``cycles`` full connect→call→disconnect lifecycles in this loop."""
    from mcp.shared.memory import create_connected_server_and_client_session
    from mcp.types import Implementation

    from knovaryn.interfaces.mcp.server import build_server

    server = build_server(database_url=db_url)
    client_info = Implementation(name="shutdown-hygiene", version="0.0.0")
    for _ in range(cycles):
        async with create_connected_server_and_client_session(
            server, client_info=client_info
        ) as session:
            result = await session.call_tool("health", {})
            text = "".join(getattr(b, "text", "") for b in result.content)
            assert '"ok"' in text, f"health failed: {text}"


def test_no_dangling_aiosqlite_workers_after_lifecycles(tmp_path: Path) -> None:
    """Every lifecycle's aiosqlite worker must terminate before its loop does."""
    db_url = f"sqlite+aiosqlite:///{tmp_path}/hygiene.db"
    baseline = _worker_thread_names()
    asyncio.run(_run_mcp_lifecycles(db_url, cycles=6))

    # Workers exit asynchronously relative to loop teardown; require them all
    # gone within a generous window rather than racing them.
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if _worker_thread_names() <= baseline:
            break
        time.sleep(0.05)
    lingering = _worker_thread_names() - baseline
    assert not lingering, f"aiosqlite worker threads leaked: {sorted(lingering)}"


def test_no_thread_exceptions_after_loop_close(tmp_path: Path) -> None:
    """Nothing may resolve against the loop once ``asyncio.run`` returned.

    This is the exact production signature of defect 3.2: a queued op future
    resolved by the aiosqlite worker after loop shutdown raises
    ``RuntimeError('Event loop is closed')`` on that thread.
    """
    db_url = f"sqlite+aiosqlite:///{tmp_path}/loopclose.db"

    captured: list[Any] = []
    previous_hook = threading.excepthook

    def hook(args: Any) -> None:
        captured.append((args.thread.name, args.exc_type, args.exc_value))

    threading.excepthook = hook
    try:
        asyncio.run(_run_mcp_lifecycles(db_url, cycles=4))
        # The loop is CLOSED from here on; any deferred resolution explodes now.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not captured:
            time.sleep(0.05)
    finally:
        threading.excepthook = previous_hook

    assert not captured, (
        "worker threads raised after loop close: "
        f"{[(n, t.__name__, str(v)) for n, t, v in captured]}"
    )


def test_server_construction_has_no_incomplete_field_warning(tmp_path: Path) -> None:
    """build_server must not emit the SDK Settings forward-ref warning."""
    recorded: list[_warnings.WarningMessage] = []
    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always")
        from knovaryn.interfaces.mcp.server import build_server

        build_server(database_url=f"sqlite+aiosqlite:///{tmp_path}/warn.db")
    recorded.extend(caught)

    offenders = [
        w for w in recorded
        if "incomplete definition" in str(w.message).lower()
        or type(w.message).__name__ == "IncompleteFieldDefinitionWarning"
    ]
    assert not offenders, (
        f"IncompleteFieldDefinitionWarning raised during build_server: "
        f"{[str(w.message)[:120] for w in offenders]}"
    )


async def _cancelled_teardown_run(db_url: str) -> None:
    """Drive one lifecycle whose teardown scope gets cancelled mid-close.

    Mirrors the production shape: the MCP SDK tears lifespans down inside a
    cancelling anyio task group, which used to abort engine disposal midway.
    Deterministic: the tool call completes first, then the enclosing scope is
    cancelled so session/teardown exit runs under cancellation.
    """
    import anyio
    from mcp.shared.memory import create_connected_server_and_client_session
    from mcp.types import Implementation

    from knovaryn.interfaces.mcp.server import build_server

    server = build_server(database_url=db_url)
    client_info = Implementation(name="cancel-teardown", version="0.0.0")
    call_done = anyio.Event()

    async def one() -> AsyncIterator[None]:
        async with create_connected_server_and_client_session(
            server, client_info=client_info
        ) as session:
            await session.call_tool("health", {})
            call_done.set()
            # hold the session open until the outer scope cancels us, so the
            # session __aexit__ (lifespan teardown → engine disposal) runs
            # inside a cancelled scope
            await anyio.sleep_forever()

    async with anyio.create_task_group() as tg:
        tg.start_soon(one)
        await call_done.wait()
        tg.cancel_scope.cancel()

    # sessions/engines must still end up fully disposed despite cancellation
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not any("_connection_worker" in t.name for t in threading.enumerate()):
            break
        await asyncio.sleep(0.05)


async def test_cancelled_teardown_disposes_completely(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path}/cancel.db"
    baseline = _worker_thread_names()
    await _cancelled_teardown_run(db_url)
    lingering = _worker_thread_names() - baseline
    assert not lingering, f"cancelled teardown left workers behind: {sorted(lingering)}"


async def test_dispose_survives_caller_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deterministic strike on the shielded ``Database.dispose`` (§3.2).

    A slow fake replaces ``engine.dispose`` so the test controls exactly
    where disposal suspends: the caller task is cancelled while blocked
    inside it, with completion withheld until afterwards — so the result
    cannot depend on scheduling speed.

    * shielded (fixed): the CALLER sees ``CancelledError``, but the inner
      disposal keeps running and finishes once released;
    * unshielded (reverted): cancellation is delivered INTO the disposal,
      killing it — it never completes.
    """
    from knovaryn.infrastructure.database.session import Database

    db = Database(f"sqlite+aiosqlite:///{tmp_path}/dispose-cancel.db")

    dispose_started = asyncio.Event()
    release_dispose = asyncio.Event()
    finished: list[bool] = []

    async def slow_dispose(*_a: object, **_k: object) -> None:
        dispose_started.set()
        await release_dispose.wait()
        finished.append(True)

    # AsyncEngine.dispose is a read-only property (instance setattr is
    # rejected), so the fake is installed on the class; monkeypatch restores
    # the property afterwards. Database.dispose resolves it through the
    # instance either way.
    monkeypatch.setattr(type(db.engine), "dispose", slow_dispose)

    async def caller() -> None:
        await db.dispose()

    task = asyncio.create_task(caller())
    await dispose_started.wait()  # disposal is now suspended mid-flight
    task.cancel()                 # strike the caller, not the disposal
    with contextlib.suppress(asyncio.CancelledError):
        await task

    release_dispose.set()  # let the in-flight disposal finish
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not finished:
        await asyncio.sleep(0.01)
    assert finished, (
        "cancelling the dispose() caller killed the disposal itself — "
        "Database.dispose() must shield engine disposal from caller cancellation"
    )


def test_sqlite_file_backend_pins_null_pool(tmp_path: Path) -> None:
    """Design pin (§3.2): SQLite backends must explicitly select NullPool.

    A pooled class keeps idle aiosqlite connections — and their worker
    threads — alive until engine disposal, which a lifespan torn down under
    cancellation may never reach cleanly. (The aiosqlite dialect's default
    pool is version-dependent, so the guarantee must not lean on it.)
    """
    import asyncio

    from sqlalchemy.pool import NullPool

    from knovaryn.infrastructure.database.session import create_engine

    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/pool-pin.db")
    try:
        assert isinstance(engine.pool, NullPool), (
            f"SQLite engine must use NullPool, found {type(engine.pool).__name__}"
        )
    finally:
        asyncio.run(engine.dispose())
