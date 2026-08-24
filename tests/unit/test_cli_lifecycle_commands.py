"""Offline behavior tests for the workspace-lifecycle CLI commands (WP J/§3.4).

Every ``knovaryn <lifecycle>`` command is a thin sync wrapper: open a
Workspace, await one service method, print, map failures to exit code 1.
These tests pin exactly that contract — argument shaping into service calls,
payload shaping out of them, JSON-vs-human output, and the exit-code rules
(succeeded→0, blocked/failed→1, service errors→1) — over a fake Workspace
injected at the same seam the real commands resolve it
(``knovaryn.application.workspace.Workspace``). No database or provider.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import knovaryn.application.workspace as ws_mod
import knovaryn.interfaces.cli.commands as commands

pytestmark = [pytest.mark.unit]


class FakeWorkspace:
    """Records calls, returns canned payloads, never touches storage."""

    instances: list[FakeWorkspace] = []
    last_principal: str | None = None

    def __init__(self, principal: str = "cli") -> None:
        self.principal = principal
        FakeWorkspace.last_principal = principal
        FakeWorkspace.instances.append(self)
        self.opened = False
        self.closed = False
        self.pipeline_kwargs: dict | None = None
        self.review_kwargs: dict | None = None
        self.publish_kwargs: dict | None = None

    @property
    def latest(self) -> FakeWorkspace:
        return FakeWorkspace.instances[-1]

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True

    # -- canned service methods ------------------------------------------------
    async def create_project(self, **kw):
        if kw["slug"] == "dup":
            raise ValueError("duplicate slug: dup")
        return SimpleNamespace(id="proj_1", slug=kw["slug"], display_name=kw["display_name"])

    async def list_projects(self, **kw):
        assert kw["limit"] >= 1
        return {"projects": [{"id": "proj_1", "slug": "a", "display_name": "A"}], "total": 1}

    async def add_source(self, **kw):
        assert isinstance(kw["raw"], bytes)
        return SimpleNamespace(id="src_1", original_name=kw["original_name"], sha256="ab" * 32)

    async def list_sources(self, **kw):
        return {"sources": [{"id": "src_1", "original_name": "a.md", "media_type": "text/plain"}]}

    async def start_pipeline(self, **kw):
        self.pipeline_kwargs = kw
        return SimpleNamespace(id="job_1")

    async def run_job(self, job_id: str):
        return {"state": "succeeded", "actual_cost": 0.0, "error_summary": None}

    async def get_job(self, job_id: str):
        if job_id == "missing":
            raise LookupError(f"no such job: {job_id}")
        return SimpleNamespace(
            to_dict=lambda: {
                "state": "succeeded",
                "current_stage": "generate",
                "progress_current": 2,
                "progress_total": 3,
            }
        )

    async def list_jobs(self, **kw):
        return {"jobs": [{"id": "job_1", "state": "succeeded"}]}

    async def list_revisions(self, *, example_id: str):
        if example_id == "ex_empty":
            return {"revisions": []}
        return {"revisions": [{"revision_id": 2}, {"revision_id": 7}]}

    async def review_example(self, **kw):
        self.review_kwargs = kw
        return {"revision": kw["revision_id"]}

    async def validate_dataset(self, **kw):
        return {"summary": {"ok": 5, "flagged": 0}, "issues": []}

    async def create_version(self, **kw):
        return SimpleNamespace(id="ver_1", semantic_version=kw.get("semantic_version") or "0.1.0")

    async def export_dataset_formatted(self, **kw):
        return SimpleNamespace(
            artifact_id="art_1",
            download_path="/tmp/export.jsonl",
            sha256="cd" * 32,
            record_count=42,
        )

    async def publish_dataset(self, **kw):
        self.publish_kwargs = kw
        return {"status": "ok", "publication_gate": {"allowed": True}}


@pytest.fixture(autouse=True)
def _reset_instances():
    FakeWorkspace.instances.clear()
    yield
    FakeWorkspace.instances.clear()


@pytest.fixture
def fake_ws(monkeypatch):
    monkeypatch.setattr(ws_mod, "Workspace", FakeWorkspace)
    return FakeWorkspace


@pytest.fixture
def flat(capsys):
    """Rich wraps console output at terminal width — collapse it for asserts."""

    class _Flat:
        out = ""

        def __call__(self):
            self.out = " ".join(capsys.readouterr().out.split())
            return self.out

    return _Flat()


# -- projects -----------------------------------------------------------------


def test_project_create_human_and_json(fake_ws, flat):
    assert commands.project_create(slug="widgets", description="d") == 0
    assert "created project widgets" in flat()
    assert commands.project_create(slug="w2", json_plain=True) == 0
    assert "w2" in flat()
    assert fake_ws.last_principal == "cli"


def test_project_create_duplicate_fails_closed(fake_ws, flat):
    assert commands.project_create(slug="dup") == 1
    assert "error:" in flat()


def test_project_list_table_and_json(fake_ws, flat):
    assert commands.project_list(limit=5) == 0
    assert "Projects" in flat()
    assert commands.project_list(json_plain=True) == 0
    assert "proj_1" in flat()


# -- sources ------------------------------------------------------------------


def test_source_add_requires_existing_file(fake_ws, flat, tmp_path):
    assert commands.source_add(project_id="p", path=tmp_path / "nope.md") == 1
    assert "not a file" in flat()


def test_source_add_ok(fake_ws, flat, tmp_path):
    f = tmp_path / "notes.txt"
    f.write_bytes(b"hello")
    rc = commands.source_add(project_id="p", path=f, license="CC-BY-4.0", privacy="public")
    assert rc == 0
    out = flat()
    assert "added source notes.txt" in out and "src_1" in out


def test_source_list_table_and_json(fake_ws, flat):
    assert commands.source_list(project_id="p") == 0
    assert "Sources" in flat()
    assert commands.source_list(project_id="p", json_plain=True) == 0
    assert "text/plain" in flat()


# -- pipeline / jobs ------------------------------------------------------------


def test_run_pipeline_succeeds(fake_ws, flat):
    rc = commands.run_pipeline(project_id="p", family="factual_explanation:2.0", target=10)
    assert rc == 0
    assert "succeeded" in flat()
    assert fake_ws.instances[-1].pipeline_kwargs["task_family_proportions"] == {
        "factual_explanation": 2.0
    }
    assert fake_ws.instances[-1].pipeline_kwargs["target_examples"] == 10


def test_run_pipeline_failed_state_is_exit_one(fake_ws, monkeypatch, flat):
    async def fail_run(self, job_id):
        return {"state": "failed", "actual_cost": 0.01, "error_summary": "boom"}

    monkeypatch.setattr(FakeWorkspace, "run_job", fail_run)
    assert commands.run_pipeline(project_id="p") == 1
    assert "failed" in flat()


def test_job_status_exit_codes(fake_ws, monkeypatch, flat):
    assert commands.job_status(job_id="job_ok") == 0
    assert "stage=generate" in flat()

    async def failed(self, job_id):
        return SimpleNamespace(to_dict=lambda: {"state": "failed"})

    monkeypatch.setattr(FakeWorkspace, "get_job", failed)
    assert commands.job_status(job_id="job_bad") == 1
    flat()

    async def missing(self, job_id):
        raise LookupError("gone")

    monkeypatch.setattr(FakeWorkspace, "get_job", missing)
    assert commands.job_status(job_id="missing") == 1
    assert "error:" in flat()


def test_job_list_table_and_json(fake_ws, flat):
    assert commands.job_list(project_id="p") == 0
    assert "Jobs" in flat()
    assert commands.job_list(json_plain=True) == 0
    assert '"state"' in flat()


# -- review ---------------------------------------------------------------------


def test_review_decide_explicit_revision(fake_ws, flat):
    rc = commands.review_decide(example_id="ex_1", decision="approve", revision=3, reviewer="amy")
    assert rc == 0
    assert fake_ws.last_principal == "amy"
    assert fake_ws.instances[-1].review_kwargs["revision_id"] == 3
    assert "recorded approve on ex_1" in flat()


def test_review_decide_resolves_latest_revision(fake_ws, flat):
    assert commands.review_decide(example_id="ex_1", decision="reject") == 0
    assert fake_ws.instances[-1].review_kwargs["revision_id"] == 7


def test_review_decide_without_revisions_fails(fake_ws, flat):
    assert commands.review_decide(example_id="ex_empty", decision="approve") == 1
    assert "no revisions" in flat()


# -- dataset lifecycle ------------------------------------------------------------


def test_dataset_validate_json_and_human(fake_ws, flat):
    assert commands.dataset_validate(project_id="p") == 0
    assert "validation summary" in flat()
    assert commands.dataset_validate(project_id="p", json_plain=True) == 0
    assert '"summary"' in flat()


def test_dataset_version(fake_ws, monkeypatch, flat):
    assert commands.dataset_version(project_id="p", semantic_version="1.2.3") == 0
    assert "1.2.3" in flat()

    async def boom(self, **kw):
        raise RuntimeError("no versions possible")

    monkeypatch.setattr(FakeWorkspace, "create_version", boom)
    assert commands.dataset_version(project_id="p") == 1
    assert "error:" in flat()


def test_dataset_export(fake_ws, monkeypatch, flat):
    assert commands.dataset_export(project_id="p", format="openai_chat") == 0
    assert "exported 42 records" in flat()
    # JSON mode exposes the full artifact identity incl. id + checksum
    assert commands.dataset_export(project_id="p", json_plain=True) == 0
    out = flat()
    assert "art_1" in out and "cdcdcdcdcdcd" in out

    async def boom(self, **kw):
        raise RuntimeError("export refused")

    monkeypatch.setattr(FakeWorkspace, "export_dataset_formatted", boom)
    assert commands.dataset_export(project_id="p") == 1
    assert "error:" in flat()


def test_dataset_publish_gate_rules(fake_ws, monkeypatch, flat):
    assert commands.dataset_publish(project_id="p", repo_id="o/r", dry_run=True) == 0
    assert "dry-run" in flat()
    assert fake_ws.instances[-1].publish_kwargs["dry_run"] is True

    async def blocked(self, **kw):
        return {"status": "blocked", "publication_gate": {"allowed": False}}

    monkeypatch.setattr(FakeWorkspace, "publish_dataset", blocked)
    assert commands.dataset_publish(project_id="p", repo_id="o/r", dry_run=False) == 1
    out = flat()
    assert "LIVE" in out and "gate_allowed=False" in out

    async def unavailable(self, **kw):
        return {"status": "unavailable"}

    monkeypatch.setattr(FakeWorkspace, "publish_dataset", unavailable)
    assert commands.dataset_publish(project_id="p", repo_id="o/r") == 1


# -- init / server / plumbing -------------------------------------------------------


def test_init_state_creates_directories(monkeypatch, tmp_path, flat):
    monkeypatch.setattr(
        commands,
        "load_config",
        lambda: {"storage": {"artifact_root": str(tmp_path / "artifacts")}},
    )
    monkeypatch.setattr(commands, "_state_dir", lambda: tmp_path / "state")
    assert commands.init_state() == 0
    assert "initialized state at" in flat()
    assert (tmp_path / "state").is_dir()
    assert (tmp_path / "artifacts").is_dir()


def test_init_state_failure_is_exit_one(monkeypatch, tmp_path, flat):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("occupied", encoding="utf-8")
    monkeypatch.setattr(
        commands,
        "load_config",
        lambda: {"storage": {"artifact_root": str(blocker)}},
    )
    monkeypatch.setattr(commands, "_state_dir", lambda: tmp_path / "state")
    assert commands.init_state() == 1
    assert "cannot create state directories" in flat()


def test_server_starts_uvicorn_on_checked_bind(monkeypatch, flat):
    seen: dict = {}

    def fake_uvicorn_run(app, host, port, reload, log_level):
        seen.update(host=host, port=port)

    monkeypatch.setattr(
        "knovaryn.interfaces.rest.security.server_bind_checked",
        lambda *, host, port: (host, port),
    )
    monkeypatch.setattr("uvicorn.run", fake_uvicorn_run)
    assert commands.server(host="127.0.0.1", port=8123) == 0
    assert seen == {"host": "127.0.0.1", "port": 8123}
    assert "Knovaryn server" in flat()


def test_server_refuses_unsafe_bind(monkeypatch, flat):
    def refuse(*, host, port):
        raise RuntimeError("refusing non-loopback bind without API token")

    monkeypatch.setattr("knovaryn.interfaces.rest.security.server_bind_checked", refuse)
    assert commands.server(host="0.0.0.0", port=8080) == 1
    assert "refusing" in flat()


def test_run_async_inside_running_loop():
    """The already-inside-a-loop branch pumps a dedicated loop to completion."""

    async def coro():
        return 41

    async def main():
        return commands._run_async(coro())

    assert asyncio.run(main()) == 41


def test_workspace_lifecycle_closes_on_error(fake_ws, monkeypatch):
    real_init = FakeWorkspace.__init__

    def tracking_init(self, principal: str = "cli") -> None:
        real_init(self, principal)

    monkeypatch.setattr(FakeWorkspace, "__init__", tracking_init)

    async def scenario():
        async with commands._workspace_lifecycle(principal="tester") as ws:
            assert ws.opened
            raise ValueError("boom")

    with pytest.raises(ValueError):  # noqa: PT012 - the point is the finally-close
        asyncio.run(scenario())
    inst = fake_ws.instances[-1]
    assert inst.closed and inst.principal == "tester"
    assert fake_ws.last_principal == "tester"


def test_print_result_modes(capsys):
    commands._print_result({"a": 1}, json_plain=True)
    out = capsys.readouterr().out
    assert '"a"' in out
    commands._print_result(None, json_plain=False, human="human message")
    assert "human message" in capsys.readouterr().out
    commands._print_result("plain", json_plain=False)
    assert "plain" in capsys.readouterr().out
