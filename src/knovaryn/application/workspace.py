"""Workspace application service (spec §17–§19).

Framework-free orchestration that binds the SQLAlchemy repositories, the
durable :class:`JobEngine`, and the :class:`ProjectService` pipeline together so
the CLI / MCP / REST surfaces share one code path.

The workspace owns a local SQLite store (``.knovaryn/knovaryn.db``) and:

* creates and lists projects,
* registers sources for a project,
* starts the offline pipeline as a durable *job* (state machine, events,
  resumability via the repository that satisfies the :class:`JobEvents`
  protocol),
* validates, versions, exports, and (dry-run) publishes dataset versions,
* records audit + cost-ledger events.

Like :class:`ProjectService`, every method is deterministic under the fake
provider and requires no credentials; a live gateway swaps in seamlessly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..domain.config import load_config
from ..domain.errors import AlreadyExistsError, NotFoundError
from ..domain.hashing import ContentHasher
from ..domain.ids import IdGenerator
from ..domain.schemas import (
    DatasetPlan,
    DatasetVersion,
    Job,
    JobState,
    Project,
    SourceDocument,
    SourceKind,
    TrainingExample,
)
from ..infrastructure.database.repositories import (
    AuditRepository,
    ExampleRepository,
    JobRepository,
    ProjectRepository,
    SourceRepository,
    VersionRepository,
)
from ..infrastructure.database.session import Database
from ..pipeline.jobs.engine import JobEngine
from ..pipeline.quality.reports import build_quality_report
from ..pipeline.quality.validators import (
    CompletenessValidator,
    FormatValidator,
    GroundingValidator,
    RefusalValidator,
    ValidatorContext,
    assemble_decision,
)
from .service import ProjectService, _split_bytes


@dataclass
class JobSummary:
    job: Job
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.job.id,
            "project_id": self.job.project_id,
            "job_type": self.job.job_type,
            "state": self.job.state.value,
            "current_stage": self.job.current_stage,
            "progress_current": self.job.progress_current,
            "progress_total": self.job.progress_total,
            "attempt_count": self.job.attempt_count,
            "estimated_cost": self.job.estimated_cost,
            "actual_cost": self.job.actual_cost,
            "created_at": self.job.created_at.isoformat() if self.job.created_at else None,
            "started_at": self.job.started_at.isoformat() if self.job.started_at else None,
            "finished_at": self.job.finished_at.isoformat() if self.job.finished_at else None,
            "error_code": self.job.error_code,
            "error_summary": self.job.error_summary,
            "events": self.events,
        }


class Workspace:
    """A project registry + durable pipeline executor on a local store."""

    def __init__(
        self,
        *,
        ids: IdGenerator | None = None,
        database_url: str | None = None,
        principal: str = "local",
    ) -> None:
        self._ids = ids or IdGenerator()
        self._principal = principal
        cfg = load_config()
        self._database_url = (
            database_url
            or cfg.get("storage.database_url")
            or "sqlite+aiosqlite:///./.knovaryn/knovaryn.db"
        )
        self._db = Database(self._database_url)

    # -- lifecycle -----------------------------------------------------------
    async def open(self) -> None:
        await self._db.create_all()

    async def close(self) -> None:
        await self._db.dispose()

    def default_project_service(self) -> ProjectService:
        return ProjectService(ids=self._ids)

    # -- projects ------------------------------------------------------------
    async def create_project(
        self,
        *,
        slug: str,
        display_name: str,
        description: str = "",
        owner_principal: str | None = None,
        tags: list[str] | None = None,
    ) -> Project:
        async with self._db.session() as session, session.begin():
            repo = ProjectRepository(session, self._ids)
            if await repo.get_by_slug(slug):
                raise AlreadyExistsError(f"project slug already exists: {slug}")
            project = Project(
                id=self._ids.new_handle("proj"),
                slug=slug,
                display_name=display_name,
                description=description,
                owner_principal=owner_principal or self._principal,
                tags=tags or [],
            )
            await repo.create(project)
            audit = AuditRepository(session, self._ids)
            await audit.record(
                principal=project.owner_principal,
                event_type="project.created",
                project_id=project.id,
                summary=f"created project {slug}",
                payload={"slug": slug},
            )
            return project

    async def get_project(self, project_id: str) -> Project:
        async with self._db.session() as session:
            repo = ProjectRepository(session, self._ids)
            project = await repo.get(project_id)
            if project is None:
                raise NotFoundError(f"project not found: {project_id}")
            return project

    async def list_projects(self, *, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
        async with self._db.session() as session:
            repo = ProjectRepository(session, self._ids)
            projects, next_cursor = await repo.list_(limit=limit, cursor=cursor)
            return {
                "projects": [p.model_dump(mode="json") for p in projects],
                "next_cursor": next_cursor,
            }

    # -- sources ---------------------------------------------------------------
    async def add_source(
        self,
        *,
        project_id: str,
        original_name: str,
        media_type: str,
        content: str,
        declared_license: str | None = None,
        source_kind: SourceKind = SourceKind.upload,
    ) -> SourceDocument:
        async with self._db.session() as session, session.begin():
            proj_repo = ProjectRepository(session, self._ids)
            if await proj_repo.get(project_id) is None:
                raise NotFoundError(f"project not found: {project_id}")
            src = SourceDocument(
                id=self._ids.new_handle("src"),
                project_id=project_id,
                original_name=original_name,
                media_type=media_type,
                byte_size=len(content.encode("utf-8")),
                sha256=ContentHasher.cfg_hash([content]),
                source_kind=source_kind,
                declared_license=declared_license,
                group_key=original_name,
                metadata={"content": content},
            )
            repo = SourceRepository(session)
            await repo.add(src)
            audit = AuditRepository(session, self._ids)
            await audit.record(
                principal=self._principal,
                event_type="source.added",
                project_id=project_id,
                summary=f"added source {original_name}",
                payload={"source_id": src.id, "bytes": src.byte_size},
            )
            return src

    async def list_sources(self, *, project_id: str, limit: int = 100) -> dict[str, Any]:
        async with self._db.session() as session:
            repo = SourceRepository(session)
            sources, next_cursor = await repo.list_by_project(project_id, limit=limit)
            return {
                "sources": [s.model_dump(mode="json") for s in sources],
                "next_cursor": next_cursor,
            }

    # -- pipeline as a durable job -------------------------------------------
    async def start_pipeline(
        self,
        *,
        project_id: str,
        task_family_proportions: dict[str, float] | None = None,
        idempotency_key: str | None = None,
    ) -> Job:
        async with self._db.session() as session, session.begin():
            proj_repo = ProjectRepository(session, self._ids)
            project = await proj_repo.get(project_id)
            if project is None:
                raise NotFoundError(f"project not found: {project_id}")
            source_repo = SourceRepository(session)
            sources, _ = await source_repo.list_by_project(project_id, limit=1000)
            if not sources:
                raise NotFoundError(f"project has no sources: {project_id}")

            job_repo = JobRepository(session, self._ids)
            if idempotency_key:
                existing = await job_repo.get_by_idempotency(idempotency_key)
                if existing is not None:
                    return existing
            job = Job(
                id=self._ids.new_handle("job"),
                project_id=project_id,
                owner_principal=project.owner_principal,
                job_type="pipeline",
                state=JobState.queued,
                idempotency_key=idempotency_key,
                input={
                    "pipeline": {"task_family_proportions": task_family_proportions or {}},
                    "source_ids": [s.id for s in sources],
                },
            )
            await job_repo.create(job)
            event = _job_event(job, "pipeline queued", event_type="queued")
            await job_repo.append_event(job.id, event)
            return job

    async def run_job(self, job_id: str) -> dict[str, Any]:
        """Resolve a queued pipeline job into a completed run (offline, in-process).

        The in-process runner acts as a single worker: it leases the job
        (``queued -> leased``) then hands it to the :class:`JobEngine`, which
        drives it ``leased -> running -> succeeded`` with durable stage
        checkpoints and events.
        """
        from ..pipeline.jobs.state import StateMachine

        async with self._db.session() as session, session.begin():
            job_repo = JobRepository(session, self._ids)
            job = await job_repo.get(job_id)
            if job is None:
                raise NotFoundError(f"job not found: {job_id}")
            # simulate a single local worker claiming the queued job
            sm = StateMachine(job.state)
            if sm.can_transition(JobState.leased):
                sm.transition(JobState.leased)
                job.state = JobState.leased
                job.lease_owner = "local-worker"
                await job_repo.save(job)
            project_repo = ProjectRepository(session, self._ids)
            project = await project_repo.get(job.project_id)
            if project is None:
                raise NotFoundError(f"project not found: {job.project_id}")
            source_repo = SourceRepository(session)
            sources, _ = await source_repo.list_by_project(job.project_id, limit=1000)
            contents = [_source_content(s) for s in sources]

            engine = JobEngine(ids=self._ids, repo=job_repo)
            stages = [
                (
                    job.job_type,
                    _make_pipeline_stage(
                        project, sources, contents, self.default_project_service()
                    ),
                )
            ]
            services: dict[str, Any] = {
                "project_id": job.project_id,
                "sources": sources,
                "contents": contents,
                "project": project,
            }
            job = await engine.run(job, stages, services=services)
            if job.state == JobState.succeeded:
                stash = job.input.get("_pipeline_result")
                if isinstance(stash, dict) and stash.get("examples"):
                    await self._persist_pipeline_result(session, job, stash)
            return job.model_dump(mode="json")

    async def _persist_pipeline_result(self, session: Any, job: Job, stash: dict[str, Any]) -> None:
        from ..domain.schemas import TrainingExample

        ex_repo = ExampleRepository(session)
        examples: list[TrainingExample] = []
        for d in stash["examples"]:
            ex = TrainingExample(**d)
            ex.project_id = job.project_id
            ex.source_document_ids = [job.project_id]
            examples.append(ex)
            await ex_repo.add(ex)
        version = stash.get("version")
        if version is None and examples:
            version = {
                "id": self._ids.new_handle("ver"),
                "project_id": job.project_id,
                "semantic_version": "0.1.0",
                "train_count": sum(1 for e in examples if e.split == "train"),
                "validation_count": sum(1 for e in examples if e.split == "validation"),
                "test_count": sum(1 for e in examples if e.split == "test"),
                "content_hash": ContentHasher.cfg_hash([e.content_hash for e in examples]),
            }
        if version is not None:
            ver_repo = VersionRepository(session)
            await ver_repo.add(DatasetVersion(**version))
            await ex_repo.assign_version(job.project_id, version["id"])
        audit = AuditRepository(session, self._ids)
        await audit.record(
            principal=job.owner_principal,
            event_type="pipeline.completed",
            project_id=job.project_id,
            summary=f"pipeline job {job.id} completed with {len(examples)} accepted examples",
            payload={
                "job_id": job.id,
                "accepted": len(examples),
                "sha256": stash.get("release_sha256", ""),
            },
        )

    async def get_job(self, job_id: str) -> JobSummary:
        async with self._db.session() as session:
            job_repo = JobRepository(session, self._ids)
            job = await job_repo.get(job_id)
            if job is None:
                raise NotFoundError(f"job not found: {job_id}")
            events, _ = await job_repo.get_events(job_id, limit=500)
            return JobSummary(job=job, events=[e.model_dump(mode="json") for e in events])

    async def list_jobs(self, *, project_id: str | None = None, limit: int = 50) -> dict[str, Any]:
        async with self._db.session() as session:
            job_repo = JobRepository(session, self._ids)
            jobs, next_cursor = await job_repo.list_(project_id=project_id, limit=limit)
            return {"jobs": [j.model_dump(mode="json") for j in jobs], "next_cursor": next_cursor}

    async def request_cancel(self, job_id: str) -> Job:
        async with self._db.session() as session, session.begin():
            job_repo = JobRepository(session, self._ids)
            job = await job_repo.get(job_id)
            if job is None:
                raise NotFoundError(f"job not found: {job_id}")
            job.cancellation_requested_at = datetime.now(UTC)
            job.state = JobState.cancelling
            await job_repo.save(job)
            return job

    # -- examples / validation -----------------------------------------------
    async def license_report(self, *, project_id: str) -> dict[str, Any]:
        """Build the source license + privacy report (spec §15) for a project."""
        from ..pipeline.license import LicenseAndPrivacyReport, SourceLicenseRecord

        async with self._db.session() as session:
            source_repo = SourceRepository(session)
            sources, _ = await source_repo.list_by_project(project_id, limit=1000)
        report = LicenseAndPrivacyReport()
        for s in sources:
            record = SourceLicenseRecord.inspect(
                source_id=s.id,
                original_name=s.original_name,
                text=_source_content(s),
                declared_license=s.declared_license,
            )
            report.add(record)
        return report.to_dict()

    async def list_examples(
        self, *, project_id: str, status: str | None = None, limit: int = 100
    ) -> dict[str, Any]:
        async with self._db.session() as session:
            ex_repo = ExampleRepository(session)
            examples, next_cursor = await ex_repo.list_by_project(
                project_id, status=status, limit=limit
            )
            return {
                "examples": [e.model_dump(mode="json") for e in examples],
                "next_cursor": next_cursor,
            }

    async def validate_dataset(self, *, project_id: str, limit: int = 500) -> dict[str, Any]:
        async with self._db.session() as session:
            ex_repo = ExampleRepository(session)
            examples, _ = await ex_repo.list_by_project(project_id, limit=limit)
            assessments = []
            topology_of: dict[str, str] = {}
            span_texts: dict[str, str] = {}
            for ex in examples:
                for c in ex.chosen_messages + ex.rejected_messages + ex.prompt_messages:
                    span_texts.setdefault("auto", c.content)
            ctx = ValidatorContext(source_texts=span_texts, policy_version="1")
            for ex in examples:
                decisions = []
                for v in (
                    GroundingValidator(),
                    CompletenessValidator(),
                    FormatValidator(),
                    RefusalValidator(),
                ):
                    decisions.append(await v.assess(ex, ctx))
                overall = assemble_decision(
                    decisions, example_id=ex.id, is_preference=(ex.topology.value == "preference")
                )
                assessments.append(overall)
                topology_of[ex.id] = ex.topology.value
            report = build_quality_report(assessments, topologies=topology_of).to_dict()
            return report

    # -- versions / export / publish ------------------------------------------
    async def create_version(
        self, *, project_id: str, semantic_version: str | None = None
    ) -> DatasetVersion:
        async with self._db.session() as session, session.begin():
            ex_repo = ExampleRepository(session)
            examples, _ = await ex_repo.list_by_project(project_id, status="accepted", limit=5000)
            version = DatasetVersion(
                id=self._ids.new_handle("ver"),
                project_id=project_id,
                semantic_version=semantic_version or "0.1.0",
                train_count=sum(1 for e in examples if e.split == "train"),
                validation_count=sum(1 for e in examples if e.split == "validation"),
                test_count=sum(1 for e in examples if e.split == "test"),
                content_hash=ContentHasher.cfg_hash([e.content_hash for e in examples]),
            )
            ver_repo = VersionRepository(session)
            await ver_repo.add(version)
            await ex_repo.assign_version(project_id, version.id)
            return version

    async def export_dataset(
        self, *, project_id: str, version_id: str | None = None
    ) -> dict[str, Any]:
        from ..pipeline.export.exporters import export_jsonl

        async with self._db.session() as session:
            ex_repo = ExampleRepository(session)
            examples, _ = await ex_repo.list_by_project(
                project_id, status="accepted", version_id=version_id, limit=5000
            )
            res = export_jsonl(list(examples), path="")
            return {
                "bytes": len(res.bytes),
                "lines": (res.bytes.decode("utf-8").count(chr(10))),
                "sha256": res.sha256,
            }

    async def publish_dataset(
        self, *, project_id: str, repo_id: str, dry_run: bool = True
    ) -> dict[str, Any]:
        """Publish (default dry-run) a project's accepted examples as a dataset.

        Enforces the §15.6 publication gate: public publication is blocked unless
        every included source has an approved redistribution decision. The gate
        status is always reported, including in dry-run mode.
        """
        from ..infrastructure.publish.hf import HFPublisher, hub_available
        from ..pipeline.export.release import build_release_bundle

        report = await self.license_report(project_id=project_id)
        gate = report["publication_gate"]
        license_summary = report["license"]
        privacy_summary = report["privacy"]

        if not hub_available():
            return {
                "status": "unavailable",
                "reason": "huggingface-hub not installed",
                "publication_gate": gate,
            }
        async with self._db.session() as session:
            ex_repo = ExampleRepository(session)
            examples, _ = await ex_repo.list_by_project(project_id, status="accepted", limit=5000)

        # §15.3/§15.6: public publication is blocked unless every source is approved.
        if not gate["allowed"]:
            return {
                "status": "blocked",
                "reason": gate["reason"],
                "unresolved": gate["unresolved"],
                "publication_gate": gate,
            }

        bundle = build_release_bundle(
            version="0.1.0",
            project_id=project_id,
            session_note="publish from workspace",
            split_files=_split_bytes(examples),
            dataset_card={"name": repo_id, "language": ["en"]},
            quality_report={},
            license_summary=license_summary,
            privacy_summary=privacy_summary,
            source_manifest={"sources": report.get("sources", [])},
            readme="# Knovaryn dataset\n",
        )
        publisher = HFPublisher(repo_id=repo_id, token=None, authorized=not dry_run)
        if dry_run:
            return {
                "status": "dry_run",
                "record": {"repo_id": repo_id, "version": "0.1.0", "revision": "", "url": ""},
                "publication_gate": gate,
            }
        record = publisher.publish_bundle(bundle, message="publish")
        return {
            "status": record.repo_id and "published",
            "record": {"repo_id": record.repo_id, "version": record.version},
            "publication_gate": gate,
        }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _job_event(
    job: Job, message: str, *, level: str = "info", event_type: str = "log", stage: str = ""
) -> Any:
    from ..domain.schemas import JobEvent

    return JobEvent(
        id=str(job.id) + ":e",
        job_id=job.id,
        timestamp=datetime.now(UTC),
        level=level,
        event_type=event_type,
        stage=stage,
        message=message,
    )


def _source_content(src: SourceDocument) -> str:
    return src.metadata.get("content", "") if src.metadata else ""


def _make_pipeline_stage(
    project: Project, sources: list[SourceDocument], contents: list[str], svc: ProjectService
) -> Callable[[Any], Awaitable[dict[str, Any]]]:
    async def stage(ctx: Any) -> dict[str, Any]:
        cfg = ctx.config or {}
        plan = DatasetPlan(
            task_family_proportions=cfg.get("task_family_proportions")
            or {"factual_explanation": 0.5, "procedure": 0.3, "comparison": 0.2}
        )
        result = await svc.run_pipeline(
            project=project, sources=sources, contents=contents, plan=plan
        )
        stash = {
            "examples": [e.model_dump(mode="json") for e in result.examples],
            "version": result.version.model_dump(mode="json") if result.version else None,
            "release_sha256": result.release_sha256,
            "quality": result.quality,
            "notes": result.notes,
        }
        ctx.job.input["_pipeline_result"] = stash
        await ctx.checkpoint("pipeline", step=1, key="result", value=result.to_dict())
        return result.to_dict()

    return stage
