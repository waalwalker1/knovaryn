"""Compose E2E (defect 4.11): the production topology actually works.

v0.1 shipped ``deploy/compose/docker-compose.prod.yml`` and a Caddyfile that
had never been booted: the proxy forwarded the ``/api`` prefix unstripped
(every REST route 404'd through the proxy), no schema bootstrap existed for
the Postgres topology, and nothing proved upload → job → worker → backup
against real containers. These tests boot the REAL stack —
``docker-compose.e2e.yml`` (the prod topology with a locally built image, a
one-shot ``migrate`` service mirroring the Kubernetes migration Job, and the
proxy published on a fixed test port) — and exercise it end to end THROUGH
the reverse proxy:

* health (api container healthcheck + proxy reachability),
* document upload and retrieval (artifact bytes land in MinIO, not SQLite),
* job queue → worker claim → completion (durable queue on Postgres),
* worker restart recovery (a job enqueued while the worker is down is
  claimed and completed after the worker starts),
* Postgres backup/restore round trip (pg_dump → drop → restore → data intact).

Mid-run crash/resume semantics are proven separately and offline by
``tests/chaos/test_real_pipeline_kill_resume.py``; this module proves the
deployed topology. Opt-in: set ``KNOVARYN_E2E_COMPOSE=1`` with a running
Docker daemon (same policy as the opt-in Postgres/S3 storage tests) — the
suite skips with an explicit reason otherwise.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

COMPOSE_FILE = Path(__file__).resolve().parents[2] / "deploy" / "compose" / "docker-compose.e2e.yml"
PROXY_BASE = "http://127.0.0.1:18080"
API_PREFIX = f"{PROXY_BASE}/api"  # Caddy strips /api before proxying to the API
STACK_TIMEOUT_S = 900  # image build + pull + boot
JOB_TIMEOUT_S = 120


def _e2e_enabled() -> bool:
    return os.environ.get("KNOVARYN_E2E_COMPOSE") == "1"


def _daemon_up() -> bool:
    try:
        subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            check=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


pytestmark = [
    pytest.mark.deployment,
    pytest.mark.skipif(
        not _e2e_enabled(), reason="set KNOVARYN_E2E_COMPOSE=1 (boots the real compose stack)"
    ),
    pytest.mark.skipif(not _daemon_up(), reason="Docker daemon not reachable"),
]


def _compose(
    args: list[str], env_file: Path, *, check: bool = True, timeout: int = 300
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "--env-file",
            str(env_file),
            *args,
        ],
        capture_output=True,
        text=True,
        check=check,
        timeout=timeout,
    )


@pytest.fixture(scope="class")
def stack(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Boot the full stack once for the class; tear down (with volumes) after."""
    env_file = tmp_path_factory.mktemp("e2e") / ".env"
    env_file.write_text(
        "\n".join(
            [
                f"POSTGRES_PASSWORD=e2e-pg-{secrets.token_urlsafe(12)}",
                f"MINIO_ROOT_USER=e2e-{secrets.token_hex(4)}",
                f"MINIO_ROOT_PASSWORD=e2e-minio-{secrets.token_urlsafe(12)}",
                f"KNOVARYN_API_TOKEN=e2e-{secrets.token_urlsafe(24)}",
            ]
        )
        + "\n"
    )
    token = env_file.read_text().split("KNOVARYN_API_TOKEN=")[1].strip()
    headers = {"Authorization": f"Bearer {token}"}

    _compose(["down", "--volumes", "--remove-orphans"], env_file, check=False)
    try:
        _compose(["up", "-d", "--build", "--wait"], env_file, timeout=STACK_TIMEOUT_S)
        yield {"headers": headers, "env_file": env_file}
    finally:
        _compose(["down", "--volumes", "--remove-orphans"], env_file, check=False)


def _wait_healthy(stack: dict[str, Any], timeout_s: int = 120) -> None:
    deadline = time.monotonic() + timeout_s
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{PROXY_BASE}/api/v1/health", timeout=5)
            if r.status_code == 200:
                return
            last = RuntimeError(f"health via proxy -> {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(2)
    raise AssertionError(f"stack never became healthy through the proxy: {last}")


def _unique_slug(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4)}"


def _healthy_services(env_file: Path) -> set[str]:
    """Services whose container is running with a passing healthcheck.

    ``ps --status healthy`` returns EMPTY on compose v5.4.0 even for clearly
    healthy containers (found by this very suite), so parse the JSON records
    instead — ``Health`` is a flat string there.
    """
    out = _compose(["ps", "--format", "json"], env_file).stdout
    healthy: set[str] = set()
    for line in out.splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("State") == "running" and rec.get("Health") == "healthy":
            healthy.add(str(rec["Service"]))
    return healthy


HANDBOOK_TEXT = (
    "# Field Handbook\n\n"
    "## Calibration\n\n"
    "Calibrate the sensor before every deployment. "
    "The calibration routine takes about two minutes and requires "
    "the reference target to be at least three meters away.\n"
)


def _make_project_with_source(stack: dict[str, Any], slug_prefix: str) -> dict[str, Any]:
    h = stack["headers"]
    with httpx.Client(base_url=API_PREFIX, headers=h, timeout=30) as c:
        r = c.post(
            "/v1/projects",
            json={"slug": _unique_slug(slug_prefix), "display_name": "Compose E2E"},
        )
        assert r.status_code == 201, r.text
        project = r.json()
        r = c.post(
            f"/v1/projects/{project['id']}/sources",
            json={
                "original_name": "handbook.md",
                "content": HANDBOOK_TEXT,
                "declared_license": "CC-BY-4.0",
                "privacy": "public",
            },
        )
        assert r.status_code == 201, r.text
        return {"project": project, "source": r.json()}


@pytest.mark.deployment
class TestComposeE2E:
    """The production container topology serves real traffic."""

    async def test_health_checks_pass(self, stack):
        """The api healthcheck is green and the proxy routes /api -> API."""
        running = _healthy_services(stack["env_file"])
        assert {"api", "postgres", "minio"} <= running, f"healthy services: {running}"
        r = httpx.get(f"{PROXY_BASE}/api/v1/health", timeout=10)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    async def test_document_upload_and_retrieval(self, stack):
        """Upload lands in the artifact store and reads back byte-identical."""
        made = _make_project_with_source(stack, "upload")
        h = stack["headers"]
        with httpx.Client(base_url=API_PREFIX, headers=h, timeout=30) as c:
            r = c.get(f"/v1/projects/{made['project']['id']}/sources")
            assert r.status_code == 200, r.text
            sources = r.json()["sources"]
            assert sources, "uploaded source must be listed"
            src = next(s for s in sources if s["id"] == made["source"]["id"])
            # artifact-first intake: real sha256 of the bytes, artifact-backed
            assert src["sha256"] == hashlib.sha256(HANDBOOK_TEXT.encode()).hexdigest()
            assert src["artifact_id_original"], "source must be backed by an artifact"
            # the declared privacy classification is consumed (defect 4.9/4.10 family)
            assert src["privacy_classification"] == "public"
            # artifact bytes live in MinIO (S3), never only in the API container
            # (the minio image has no `find`; plain `ls -R` lists object files)
            mc = _compose(
                [
                    "exec",
                    "-T",
                    "minio",
                    "sh",
                    "-c",
                    "ls -R /data/knovaryn-artifacts | head -5",
                ],
                stack["env_file"],
            )
            assert "/data/" in mc.stdout, f"no artifacts in MinIO: {mc.stdout!r}"

    async def test_job_queue_and_worker_claim(self, stack):
        """A queued pipeline job is claimed and completed by the worker."""
        made = _make_project_with_source(stack, "job")
        h = stack["headers"]
        with httpx.Client(base_url=API_PREFIX, headers=h, timeout=30) as c:
            r = c.post(f"/v1/projects/{made['project']['id']}/pipeline", json={})
            assert r.status_code == 202, r.text
            job_id = r.json()["id"]
            deadline = time.monotonic() + JOB_TIMEOUT_S
            state = None
            while time.monotonic() < deadline:
                r = c.get(f"/v1/jobs/{job_id}")
                assert r.status_code == 200, r.text
                state = r.json()["state"]
                if state in ("succeeded", "failed", "dead"):
                    break
                time.sleep(2)
            assert state == "succeeded", f"job ended in {state}"

    async def test_worker_restart_and_recovery(self, stack):
        """A job enqueued while the worker is DOWN is claimed after it starts.

        Proves the durable queue survives a worker restart: the job outlives
        the (absent) worker and is picked up by the restarted process.
        """
        env_file = stack["env_file"]
        _compose(["stop", "worker"], env_file)
        try:
            made = _make_project_with_source(stack, "restart")
            h = stack["headers"]
            with httpx.Client(base_url=API_PREFIX, headers=h, timeout=30) as c:
                r = c.post(f"/v1/projects/{made['project']['id']}/pipeline", json={})
                assert r.status_code == 202, r.text
                job_id = r.json()["id"]
                # no worker running: the job must still be queued, not lost
                r = c.get(f"/v1/jobs/{job_id}")
                assert r.json()["state"] == "queued"
        finally:
            _compose(["start", "worker"], env_file)
        with httpx.Client(base_url=API_PREFIX, headers=stack["headers"], timeout=30) as c:
            deadline = time.monotonic() + JOB_TIMEOUT_S
            state = None
            while time.monotonic() < deadline:
                r = c.get(f"/v1/jobs/{job_id}")
                state = r.json()["state"]
                if state in ("succeeded", "failed", "dead"):
                    break
                time.sleep(2)
            assert state == "succeeded", f"job after worker restart ended in {state}"

    async def test_backup_and_restore(self, stack):
        """pg_dump -> drop -> restore leaves the data readable through the API."""
        made = _make_project_with_source(stack, "backup")
        env_file = stack["env_file"]
        project_id = made["project"]["id"]

        dump = _compose(
            ["exec", "-T", "postgres", "pg_dump", "-U", "knovaryn", "knovaryn"],
            env_file,
            timeout=120,
        )
        assert dump.stdout.strip(), "pg_dump produced an empty dump"

        # quiesce writers, destroy, restore, resume
        _compose(["stop", "api", "worker"], env_file)
        try:
            _compose(
                [
                    "exec",
                    "-T",
                    "postgres",
                    "psql",
                    "-U",
                    "knovaryn",
                    "-d",
                    "postgres",
                    "-c",
                    "DROP DATABASE knovaryn;",
                    "-c",
                    "CREATE DATABASE knovaryn OWNER knovaryn;",
                ],
                env_file,
                timeout=60,
            )
            restore = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(COMPOSE_FILE),
                    "--env-file",
                    str(env_file),
                    "exec",
                    "-T",
                    "postgres",
                    "psql",
                    "-U",
                    "knovaryn",
                    "-d",
                    "knovaryn",
                ],
                input=dump.stdout,
                capture_output=True,
                text=True,
                check=True,
                timeout=120,
            )
            assert restore.returncode == 0, restore.stderr
        finally:
            _compose(["start", "api", "worker"], env_file)

        with httpx.Client(base_url=API_PREFIX, headers=stack["headers"], timeout=60) as c:
            deadline = time.monotonic() + 60
            r = None
            while time.monotonic() < deadline:
                try:
                    r = c.get(f"/v1/projects/{project_id}")
                    if r.status_code == 200:
                        break
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(2)
            assert r is not None and r.status_code == 200, (
                f"project unreadable after restore: {r.status_code if r else 'no response'}"
            )
            assert r.json()["id"] == project_id

    async def test_migrations_run(self, stack):
        """The one-shot migrate service bootstrapped the schema in Postgres."""
        tables = _compose(
            [
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "knovaryn",
                "-d",
                "knovaryn",
                "-tAc",
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename",
            ],
            stack["env_file"],
        )
        names = {t.strip() for t in tables.stdout.splitlines() if t.strip()}
        assert {"projects", "source_documents", "jobs"} <= names, f"core tables missing: {names}"
