"""Chaos test: kill a worker mid-REAL-pipeline, reclaim, resume (spec §7, §12).

Unlike the synthetic-stage P0-5 test, this exercises the production pipeline
stage shape — the same one the CLI worker installs (``pipeline`` stage running
``ProjectService.run_pipeline`` over the job's project + sources) — with:

* a real ``ModelGateway`` (fake models) wired to the durable ``model_calls``
  ledger and a ``CallCache`` over a real filesystem artifact store,
* a hard worker death mid-pipeline (the process dies; nothing cleans up — the
  job row stays ``running`` with a lease that then expires),
* a replacement worker that reclaims the expired-lease job and resumes it
  through the ``JobEngine``.

Guarantees proven:
  1. the reclaimed job resumes to ``succeeded`` and produces examples,
  2. no logical provider call is paid twice across the kill+resume
     (total fake-provider invocations == unique request fingerprints),
  3. no duplicate cost events in ``model_calls`` (one row per fingerprint),
  4. the resumed dataset is byte-identical (by content hash) to an
     uninterrupted reference run of the same inputs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from knovaryn.application.service import ProjectService
from knovaryn.application.workspace import Workspace
from knovaryn.domain.errors import KnovarynError
from knovaryn.domain.ids import IdGenerator
from knovaryn.domain.schemas import DatasetPlan, JobState
from knovaryn.infrastructure.artifacts.local import LocalArtifactStore
from knovaryn.infrastructure.database.repositories import ModelCallRepository
from knovaryn.infrastructure.models.call_cache import CallCache
from knovaryn.infrastructure.models.fake_provider import FakeProvider
from knovaryn.infrastructure.models.gateway import ModelGateway
from knovaryn.pipeline.jobs.engine import JobEngine
from knovaryn.pipeline.jobs.retry import RetryPolicy
from knovaryn.pipeline.jobs.worker import WorkerRepository

_SECTIONS = [
    ("# Widget handbook", "A widget converts pressure into rotation. The valve regulates intake."),
    (
        "## Maintenance",
        "Inspect the valve monthly. Replace the gasket when pressure drops below 2 bar.",
    ),
    ("## Assembly", "Seat the rotor, torque the housing to 12 Nm, then calibrate the governor."),
    ("## Comparison", "Compared with rotor-X, the rotor-Y runs cooler but delivers less torque."),
    (
        "## Troubleshooting",
        "If the governor oscillates, check the spring tension and the intake screen.",
    ),
    ("## Lubrication", "Apply synthetic grease to the bearing race every 500 operating hours."),
    ("## Storage", "Store widgets in a dry room below 30 C. Keep the valve open during storage."),
    ("## Safety", "Depressurize the intake line before removing the valve cap."),
    ("## Calibration", "Zero the governor against the reference gauge before each production run."),
    ("## Wear limits", "Replace the rotor when radial play exceeds 0.2 mm at the seal face."),
    ("## Diagnostics", "A rising intake temperature with constant load indicates a fouled screen."),
    ("## Spare parts", "Keep one gasket set and one governor spring per operating widget on site."),
]

_SOURCE = "\n\n".join(f"{h}\n\n{b}" for h, b in _SECTIONS)


class WorkerDied(KnovarynError):
    """Simulates hard process death — nothing catches it, nothing cleans up."""

    code = "worker_died"

    def __init__(self) -> None:
        super().__init__("worker process killed mid-pipeline")


class CrashingFake(FakeProvider):
    """FakeProvider that dies hard on the (crash_after+1)-th invocation."""

    def __init__(self, crash_after: int, **kw: Any) -> None:
        super().__init__(**kw)
        self.calls: list[dict[str, Any]] = []
        self.crash_after = crash_after

    async def complete(self, **kw: Any) -> dict[str, Any]:  # type: ignore[override]
        if len(self.calls) >= self.crash_after:
            raise WorkerDied()
        self.calls.append(dict(kw))
        return await super().complete(**kw)


class HealthyFake(FakeProvider):
    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.calls: list[dict[str, Any]] = []

    async def complete(self, **kw: Any) -> dict[str, Any]:  # type: ignore[override]
        self.calls.append(dict(kw))
        return await super().complete(**kw)


class LedgerAdapter:
    """Per-op session adapter for ModelCallRepository (WorkerRepository pattern)."""

    def __init__(self, db: Any, ids: IdGenerator) -> None:
        self._db = db
        self._ids = ids

    async def record(self, call: dict[str, Any]) -> None:
        async with self._db.session() as session, session.begin():
            await ModelCallRepository(session, self._ids).record(call)

    async def get_by_fingerprint(self, job_id: str, fingerprint: str) -> Any:
        async with self._db.session() as session:
            return await ModelCallRepository(session, self._ids).get_by_fingerprint(
                job_id, fingerprint
            )


@pytest.fixture
async def workspace(tmp_path: Path) -> Workspace:
    db = tmp_path / "knovaryn-kill.db"
    ws = Workspace(database_url=f"sqlite+aiosqlite:///{db}", principal="test")
    await ws.open()
    yield ws
    await ws.close()


def _pipeline_stage(
    ws: Workspace,
    ids: IdGenerator,
    artifact_root: Path,
    fake: FakeProvider,
    job_id: str,
) -> Any:
    """The production pipeline stage (CLI worker shape) with a real gateway."""

    async def stage(ctx: Any) -> dict[str, Any]:
        from knovaryn.infrastructure.database.repositories import (
            ProjectRepository,
            SourceRepository,
        )

        job = ctx.job
        async with ws._db.session() as session, session.begin():
            project = await ProjectRepository(session, ids).get(job.project_id)
            if project is None:
                raise RuntimeError(f"project not found: {job.project_id}")
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

        pipeline_cfg = (job.input or {}).get("pipeline", {}) or {}
        plan = DatasetPlan(
            task_family_proportions=pipeline_cfg.get("task_family_proportions")
            or {"factual_explanation": 0.5, "procedure": 0.3, "comparison": 0.2}
        )
        gateway = ModelGateway(
            generator_model="fake",
            critic_model="fake",
            verifier_model="fake",
            fake=fake,
            call_cache=CallCache(store=LocalArtifactStore(artifact_root)),
            model_call_repo=LedgerAdapter(ws._db, ids),
            project_id=job.project_id,
            job_id=job.id,
            stage="generate",
        )
        svc = ProjectService(ids=ids, gateway=gateway)
        result = await svc.run_pipeline(
            project=project, sources=sources, contents=contents, plan=plan
        )
        ctx.job.input["_pipeline_result"] = {
            "examples": [e.model_dump(mode="json") for e in result.examples],
        }
        await ctx.checkpoint("pipeline", step=1, key="result", value=result.to_dict())
        return result.to_dict()

    return stage


async def _ledger_fingerprints(ws: Workspace, job_id: str) -> list[str]:
    from sqlalchemy import select

    from knovaryn.infrastructure.database.models import ModelCallDB

    async with ws._db.session() as session:
        rows = (
            (
                await session.execute(
                    select(ModelCallDB.request_fingerprint).where(ModelCallDB.job_id == job_id)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)


class TestRealPipelineKillResume:
    async def test_kill_mid_pipeline_resume_completes_without_double_payment(
        self, workspace: Workspace, tmp_path: Path
    ) -> None:
        ids = IdGenerator()
        artifact_root = tmp_path / "artifacts"
        proj = await workspace.create_project(slug="kill", display_name="Kill Resume")
        await workspace.add_source(
            project_id=proj.id,
            original_name="handbook.md",
            media_type="text/markdown",
            content=_SOURCE,
        )
        job = await workspace.start_pipeline(project_id=proj.id, task_family_proportions={})
        repo = WorkerRepository(workspace._db, ids)

        # ---- pass A: worker claims, starts running, DIES mid-pipeline ------
        claimed = await repo.claim_eligible(worker="worker-a", lease_seconds=300)
        assert claimed is not None and claimed.id == job.id
        claimed.state = JobState.running  # engine's first save, then process death
        await repo.save(claimed)

        crashing = CrashingFake(crash_after=2)
        stage_a = _pipeline_stage(workspace, ids, artifact_root, crashing, job.id)

        class _Ctx:
            job = claimed
            checkpoint_sequence = 0

            async def checkpoint(self, *a: Any, **k: Any) -> None:  # pragma: no cover
                raise AssertionError("pass A must die before any checkpoint commits")

        with pytest.raises(WorkerDied):
            await stage_a(_Ctx())

        assert len(crashing.calls) == 2, (
            "pass A must complete exactly crash_after paid calls before dying"
        )

        # nothing cleaned up: the job row is still running, lease now expiring
        async with workspace._db.session() as session, session.begin():
            from knovaryn.infrastructure.database.repositories import JobRepository

            jrepo = JobRepository(session, ids)
            orphan = await jrepo.get(job.id)
            assert orphan is not None
            assert orphan.state == JobState.running
            orphan.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await jrepo.save(orphan)

        # ---- pass B: replacement worker reclaims and resumes ---------------
        reclaimed = await repo.claim_eligible(worker="worker-b", lease_seconds=300)
        assert reclaimed is not None and reclaimed.id == job.id, (
            "expired-lease running job must be reclaimable"
        )

        healthy = HealthyFake()
        stage_b = _pipeline_stage(workspace, ids, artifact_root, healthy, job.id)
        engine = JobEngine(ids=ids, repo=repo, retry_policy=RetryPolicy())
        result = await engine.run(
            reclaimed, [("pipeline", stage_b)], services={"job.input": reclaimed.input}
        )

        assert result.state == JobState.succeeded
        stash = result.input.get("_pipeline_result") or {}
        assert stash.get("examples"), "resumed pipeline must produce examples"

        # ---- guarantee 2: no logical provider call paid twice --------------
        total_invocations = len(crashing.calls) + len(healthy.calls)
        fps = await _ledger_fingerprints(workspace, job.id)
        unique_fps = set(fps)
        assert total_invocations == len(unique_fps), (
            f"paid provider calls duplicated across kill+resume: "
            f"{total_invocations} invocations vs {len(unique_fps)} unique fingerprints"
        )
        assert len(crashing.calls) + len(healthy.calls) >= 3, "scenario too small to be meaningful"

        # ---- guarantee 3: no duplicate cost events -------------------------
        assert len(fps) == len(unique_fps), (
            f"duplicate cost events in model_calls: {len(fps)} rows, "
            f"{len(unique_fps)} unique fingerprints"
        )

        # ---- guarantee 4: resumed output identical to a clean reference ----
        ref_ids = IdGenerator()
        ref_ws_db = tmp_path / "ref.db"
        ref_ws = Workspace(database_url=f"sqlite+aiosqlite:///{ref_ws_db}", principal="test")
        await ref_ws.open()
        try:
            ref_proj = await ref_ws.create_project(slug="ref", display_name="Reference")
            await ref_ws.add_source(
                project_id=ref_proj.id,
                original_name="handbook.md",
                media_type="text/markdown",
                content=_SOURCE,
            )
            ref_fake = HealthyFake()
            ref_gateway = ModelGateway(
                generator_model="fake",
                critic_model="fake",
                verifier_model="fake",
                fake=ref_fake,
                call_cache=CallCache(store=LocalArtifactStore(tmp_path / "ref-artifacts")),
                project_id=ref_proj.id,
                stage="generate",
            )
            ref_svc = ProjectService(ids=ref_ids, gateway=ref_gateway)
            from knovaryn.infrastructure.database.repositories import SourceRepository

            async with ref_ws._db.session() as session:
                sources, _ = await SourceRepository(session).list_by_project(ref_proj.id, limit=100)
            contents = [(s.metadata or {}).get("content", "") or "" for s in sources]
            ref_result = await ref_svc.run_pipeline(
                project=ref_proj,
                sources=sources,
                contents=contents,
                plan=DatasetPlan(
                    task_family_proportions={
                        "factual_explanation": 0.5,
                        "procedure": 0.3,
                        "comparison": 0.2,
                    }
                ),
            )
            ref_hashes = sorted(e.content_hash for e in ref_result.examples)
            resumed_hashes = sorted(e["content_hash"] for e in stash["examples"])
            assert resumed_hashes == ref_hashes, (
                "kill+resume changed the dataset — resume is not deterministic"
            )
        finally:
            await ref_ws.close()
