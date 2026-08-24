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

import asyncio
import base64
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


def _minimal_pdf(text: str) -> bytes:
    """Build a real single-page PDF carrying ``text`` (§3.10 step 3).

    Objects are written with a genuine xref table (offsets computed while
    writing) so parsers do not need to fall back to repair heuristics.
    """
    escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    stream = f"BT /F1 14 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []

    def _obj(num: int, body: bytes) -> None:
        offsets.append(len(out))
        out.extend(f"{num} 0 obj\n".encode("ascii"))
        out.extend(body)
        out.extend(b"\nendobj\n")

    _obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    _obj(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    _obj(
        3,
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    )
    _obj(4, b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    _obj(5, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    xref_at = len(out)
    out.extend(f"xref\n0 {len(offsets) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(offsets) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


_CLAIM_SCRIPT = """
import asyncio, os, sys
from knovaryn.domain.ids import IdGenerator
from knovaryn.infrastructure.database.session import Database
from knovaryn.infrastructure.database.repositories import JobRepository

async def main() -> None:
    db = Database(os.environ["KNOVARYN_STORAGE_DATABASE_URL"])
    async with db.session() as session, session.begin():
        repo = JobRepository(session, IdGenerator())
        job = await repo.claim_eligible(worker=sys.argv[1], lease_seconds=120)
        print(job.id if job is not None else "NONE")

asyncio.run(main())
"""


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

    async def test_binary_pdf_upload(self, stack):
        """A real binary PDF goes through intake: sniffed type, real sha256,
        artifact bytes in object storage (§3.10 steps 3–4)."""
        pdf = _minimal_pdf(
            "Calibrate the sensor before every deployment. The reference "
            "target must be at least three meters away."
        )
        h = stack["headers"]
        with httpx.Client(base_url=API_PREFIX, headers=h, timeout=30) as c:
            r = c.post(
                "/v1/projects",
                json={"slug": _unique_slug("pdf"), "display_name": "Compose E2E PDF"},
            )
            assert r.status_code == 201, r.text
            project = r.json()
            r = c.post(
                f"/v1/projects/{project['id']}/sources",
                json={
                    "original_name": "handbook.pdf",
                    "raw": base64.b64encode(pdf).decode("ascii"),
                    "declared_license": "CC-BY-4.0",
                    "privacy": "public",
                },
            )
            assert r.status_code == 201, r.text
            src = r.json()
            # binary truth, not the caller's declaration
            assert src["sha256"] == hashlib.sha256(pdf).hexdigest()
            assert src["byte_size"] == len(pdf)
            assert "pdf" in (src.get("media_type") or ""), (
                f"PDF not detected as binary PDF: {src.get('media_type')!r}"
            )
            assert src["artifact_id_original"], "binary source must be artifact-backed"

    async def test_pipeline_provenance_version_export(self, stack):
        """After a successful job: provenance on examples, dataset version,
        export with checksum + recorded span precision (§3.10 steps 8–11)."""
        made = _make_project_with_source(stack, "export")
        h = stack["headers"]
        pid = made["project"]["id"]
        with httpx.Client(base_url=API_PREFIX, headers=h, timeout=60) as c:
            r = c.post(f"/v1/projects/{pid}/pipeline", json={})
            assert r.status_code == 202, r.text
            job_id = r.json()["id"]
            deadline = time.monotonic() + JOB_TIMEOUT_S
            state = None
            while time.monotonic() < deadline:
                r = c.get(f"/v1/jobs/{job_id}")
                state = r.json()["state"]
                if state in ("succeeded", "failed", "dead"):
                    break
                time.sleep(2)
            assert state == "succeeded", f"job ended in {state}"

            # semantic quality validation ran as part of the pipeline and is
            # re-runnable over the persisted examples (step 8)
            r = c.post(f"/v1/projects/{pid}/validate")
            assert r.status_code == 200, r.text
            report = r.json()
            assert "summary" in report or "counts" in report or "checks" in report

            # examples carry provenance; lineage resolves to spans with a
            # machine-verifiable precision vocabulary (steps 9 + 16)
            r = c.get(f"/v1/projects/{pid}/examples")
            assert r.status_code == 200, r.text
            examples = r.json().get("examples", [])
            assert examples, "pipeline produced no examples"
            ex = examples[0]
            assert ex["source_span_ids"] or ex["source_document_ids"], (
                "example carries no provenance"
            )
            r = c.get(f"/v1/projects/{pid}/examples/{ex['id']}/lineage")
            assert r.status_code == 200, r.text
            lineage = r.json()
            for span in lineage.get("source_spans", []):
                precision = span.get("precision")
                assert precision in {
                    "exact_bbox", "exact_page", "page_range", "section", "chunk", "unknown"
                }, f"span precision {precision!r} outside the honest vocabulary"

            # version -> export -> checksum metadata (steps 10–11)
            r = c.post(f"/v1/projects/{pid}/version", json={})
            assert r.status_code == 201, r.text
            version = r.json()
            assert version["member_example_ids"], "version froze zero examples"
            r = c.post(f"/v1/projects/{pid}/export", json={"version_id": version["id"]})
            assert r.status_code in (200, 201), r.text
            export = r.json()

            def _find_sha(node: object) -> str | None:
                if isinstance(node, dict):
                    for k, v in node.items():
                        if k in ("sha256", "content_sha256") and isinstance(v, str) and len(v) == 64:
                            return v
                        found = _find_sha(v)
                        if found:
                            return found
                elif isinstance(node, list):
                    for item in node:
                        found = _find_sha(item)
                        if found:
                            return found
                return None

            assert _find_sha(export), f"export response carries no checksum: {export}"

    async def test_two_workers_cannot_claim_same_job(self, stack):
        """FOR UPDATE SKIP LOCKED claim exclusivity on real Postgres (§3.10).

        With the worker stopped, one queued job is offered to two concurrent
        claimers racing through separate transactions: exactly one wins, the
        other gets nothing — no double claim, no double provider spend.
        """
        env_file = stack["env_file"]
        _compose(["stop", "worker"], env_file)
        try:
            made = _make_project_with_source(stack, "claim")
            h = stack["headers"]
            with httpx.Client(base_url=API_PREFIX, headers=h, timeout=30) as c:
                r = c.post(f"/v1/projects/{made['project']['id']}/pipeline", json={})
                assert r.status_code == 202, r.text
                job_id = r.json()["id"]

            script_name = f"claim_job_{secrets.token_hex(4)}.py"
            script_path = Path("/tmp") / script_name
            script_path.write_text(_CLAIM_SCRIPT)
            _compose(["cp", str(script_path), f"api:/tmp/{script_name}"], env_file)
            script_path.unlink(missing_ok=True)

            async def _claim(name: str) -> str:
                proc = await asyncio.create_subprocess_exec(
                    "docker", "compose", "-f", str(COMPOSE_FILE),
                    "--env-file", str(env_file),
                    "exec", "-T", "api", "python", f"/tmp/{script_name}", name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                out, err = await asyncio.wait_for(proc.communicate(), timeout=120)
                assert proc.returncode == 0, err.decode()
                line = out.decode().strip().splitlines()[-1]
                return line.strip()

            got_a, got_b = await asyncio.gather(_claim("worker-a"), _claim("worker-b"))
            winners = {w for w in (got_a, got_b) if w != "NONE"}
            assert winners == {job_id}, (
                f"claim race broken: a={got_a!r}, b={got_b!r}, expected exactly {{{job_id}}}"
            )

            # the lease is alive for another ~120s: nobody else can claim it
            got_again = await _claim("worker-c")
            assert got_again == "NONE", f"leased job was claimed again: {got_again!r}"
        finally:
            _compose(["start", "worker"], env_file)

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

            # §3.10 step 16: post-restore lineage + artifact verification —
            # restored rows must still resolve provenance end to end.
            r = c.get(f"/v1/projects/{project_id}/sources")
            assert r.status_code == 200, r.text
            sources = r.json().get("sources", [])
            assert sources, "sources lost by restore"
            src = next(
                s for s in sources if s["id"] == made["source"]["id"]
            )
            assert src["sha256"] == hashlib.sha256(HANDBOOK_TEXT.encode()).hexdigest()
            assert src["artifact_id_original"], "artifact binding lost by restore"

            r = c.post(f"/v1/projects/{project_id}/pipeline", json={})
            assert r.status_code == 202, r.text
            job_id = r.json()["id"]
            deadline = time.monotonic() + JOB_TIMEOUT_S
            state = None
            while time.monotonic() < deadline:
                rr = c.get(f"/v1/jobs/{job_id}")
                state = rr.json()["state"]
                if state in ("succeeded", "failed", "dead"):
                    break
                time.sleep(2)
            assert state == "succeeded", f"post-restore pipeline ended in {state}"
            r = c.get(f"/v1/projects/{project_id}/examples")
            assert r.status_code == 200, r.text
            examples = r.json().get("examples", [])
            assert examples, "no examples after post-restore run"
            r = c.get(f"/v1/projects/{project_id}/examples/{examples[0]['id']}/lineage")
            assert r.status_code == 200, r.text
            assert r.json().get("source_document_ids"), "lineage empty after restore"

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
