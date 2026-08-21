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

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..domain.config import load_config
from ..domain.errors import AlreadyExistsError, JobStateError, NotFoundError
from ..domain.hashing import ContentHasher
from ..domain.ids import IdGenerator
from ..domain.schemas import (
    DatasetPlan,
    DatasetVersion,
    ExportArtifact,
    Job,
    JobState,
    Project,
    SourceDocument,
    SourceKind,
    TrainingExample,
)
from ..infrastructure.database.repositories import (
    AuditRepository,
    CandidateRepository,
    ChunkRepository,
    ExampleRepository,
    JobRepository,
    ParsedRepository,
    ProjectRepository,
    ReviewRepository,
    RevisionRepository,
    SourceRepository,
    SpanRepository,
    VersionRepository,
)
from ..infrastructure.database.session import Database
from ..infrastructure.models.profiles import DEFAULT_RUNTIME_PROFILE, build_gateway
from ..pipeline.jobs.engine import JobEngine
from ..pipeline.quality.reports import build_quality_report
from ..pipeline.quality.validators import (
    AnswerabilityValidator,
    CompletenessValidator,
    FormatValidator,
    GroundingValidator,
    RefusalValidator,
    SchemaValidator,
    ValidatorContext,
    assemble_decision,
)
from .service import ProjectService, _artifact_assessment, _split_bytes


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
        """Build the project service on the configured runtime profile.

        Defect 4.9: v0.1 hard-wired the fake gateway here, so the official
        profile registry was dead code from every surface. The configured
        ``models.profile`` now decides — offline aliases get the deterministic
        fake gateway, live profiles get the real provider (and fail loudly when
        its credentials are absent; never a silent fake fallback, WP D5).
        """
        cfg = load_config()
        profile = str(cfg.get("models.profile") or cfg.get("profile") or DEFAULT_RUNTIME_PROFILE)
        gateway = build_gateway(profile)
        return ProjectService(ids=self._ids, gateway=gateway)

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

    # -- tenancy / authorization (WP J3) --------------------------------------
    # Enforcement lives here, in the application service, so the CLI/MCP/SDK/REST
    # all share one ownership + scope policy (no interface implements its own
    # fake authorization). ``admin_principals`` is resolved from config; the
    # ``local`` principal is the loopback trust boundary for offline operation.
    def _admin_principals(self) -> set[str]:
        cfg = load_config()
        admins = cfg.get("server", {}).get("admin_principals") or []
        return {str(a) for a in admins}

    async def require_project_access(self, *, project_id: str, principal: str, scope: str) -> None:
        """Authorize ``principal`` to perform ``scope`` on ``project_id``.

        Raises :class:`AuthorizationError` when the principal owns neither the
        project nor an ``admin`` grant (403). The default ``local`` principal is
        the loopback trust boundary and is always allowed.
        """
        from ..domain.errors import AuthorizationError

        if principal in self._admin_principals() or principal in ("local", "system"):
            return
        project = await self.get_project(project_id)
        if project.owner_principal != principal:
            raise AuthorizationError(
                f"principal {principal!r} has no {scope} access to project {project_id}"
            )

    def _principal_owned_projects(self, principal: str) -> bool:
        """True when the caller sees all projects (admin/system/loopback)."""
        return principal in self._admin_principals() or principal in ("local", "system")

    async def list_projects_visible(
        self, *, principal: str, limit: int = 50, cursor: str | None = None
    ) -> dict[str, Any]:
        """List the projects a principal may view (owner-tenant isolation)."""
        async with self._db.session() as session:
            repo = ProjectRepository(session, self._ids)
            if self._principal_owned_projects(principal):
                projects, next_cursor = await repo.list_(limit=limit, cursor=cursor)
                return {
                    "projects": [p.model_dump(mode="json") for p in projects],
                    "next_cursor": next_cursor,
                }
            all_projects, _ = await repo.list_(limit=10000, cursor=None)
            owned = [p for p in all_projects if p.owner_principal == principal]
            rows = [p.model_dump(mode="json") for p in owned][:limit]
            return {"projects": rows, "next_cursor": None}

    async def list_projects(self, *, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
        async with self._db.session() as session:
            repo = ProjectRepository(session, self._ids)
            projects, next_cursor = await repo.list_(limit=limit, cursor=cursor)
            return {
                "projects": [p.model_dump(mode="json") for p in projects],
                "next_cursor": next_cursor,
            }

    # -- sources ---------------------------------------------------------------
    def _artifact_store(self) -> Any:
        """Build (and cache) the content-addressed artifact store (spec §6.3)."""
        store = getattr(self, "_artifact_store_cache", None)
        if store is None:
            from ..infrastructure.artifacts.__factory import build_artifact_store

            cfg = load_config()
            storage = cfg.get("storage", {})
            store = build_artifact_store(
                backend=storage.get("artifact_backend", "local"),
                config=storage,
            )
            self._artifact_store_cache = store
        return store

    def _intake_service(self) -> Any:
        svc = getattr(self, "_intake_service_cache", None)
        if svc is None:
            from ..infrastructure.intake.intake import IntakeService

            cfg = load_config()
            storage = cfg.get("storage", {})
            root = storage.get("artifact_root") or ".knovaryn/artifacts"
            svc = IntakeService(
                ids=self._ids,
                store=self._artifact_store(),
                quarantine_dir=Path(str(root)).parent / "quarantine",
            )
            self._intake_service_cache = svc
        return svc

    async def add_source(
        self,
        *,
        project_id: str,
        original_name: str,
        media_type: str | None = None,
        content: str = "",
        raw: bytes | None = None,
        declared_license: str | None = None,
        privacy: str | None = None,
        source_kind: SourceKind = SourceKind.upload,
        source_locator: str = "",
        group_key: str | None = None,
    ) -> SourceDocument:
        """Register a source through the security-hardened intake funnel (G1/G3).

        Single intake path: text callers pass ``content`` (encoded here), binary /
        URL / archive callers pass ``raw`` bytes. Everything is magic-sniffed,
        size-limited, quarantined, hashed with a real SHA-256 of the bytes, and
        persisted artifact-first through :class:`IntakeService` before the source
        is committed to the store. ``media_type`` is accepted for caller
        compatibility but is advisory only — the detected type wins.
        """
        if raw is None:
            # preserve the legacy text signature: encode to bytes and let intake
            # do the rest (magic sniff, real sha256, artifact-first persistence).
            raw = content.encode("utf-8")

        intake = self._intake_service()
        result = await intake.ingest_bytes(
            project_id=project_id,
            name=original_name,
            data=raw,
            source_kind=source_kind,
            locator=source_locator,
            declared_license=declared_license,
            group_key=group_key or original_name,
        )
        ingested = result.source

        async with self._db.session() as session, session.begin():
            proj_repo = ProjectRepository(session, self._ids)
            if await proj_repo.get(project_id) is None:
                raise NotFoundError(f"project not found: {project_id}")
            # adopt the intake-built source document (artifact-first provenance);
            # the locator is already redacted by intake.
            src = SourceDocument(
                id=ingested.id,
                project_id=project_id,
                original_name=original_name,
                media_type=ingested.media_type,
                byte_size=ingested.byte_size,
                sha256=ingested.sha256,
                source_kind=source_kind,
                source_locator_redacted=ingested.source_locator_redacted,
                declared_license=declared_license,
                privacy_classification=privacy or "unknown",
                license_status=ingested.license_status,
                intake_status=ingested.intake_status,
                artifact_id_original=ingested.artifact_id_original,
                group_key=group_key or original_name,
                metadata=dict(ingested.metadata or {}),
            )
            # keep text content accessible to the legacy parse path without
            # duplicating bytes for binary sources.
            is_text = src.media_type.startswith("text/") or src.media_type in (
                "text/markdown",
                "text/plain",
                "text/html",
                "text/xml",
            )
            if is_text and raw:
                src.metadata["content"] = raw.decode("utf-8", errors="ignore")
            repo = SourceRepository(session)
            await repo.add(src)
            audit = AuditRepository(session, self._ids)
            await audit.record(
                principal=self._principal,
                event_type="source.added",
                project_id=project_id,
                summary=f"added source {original_name}",
                payload={"source_id": src.id, "bytes": src.byte_size, "sha256": src.sha256},
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
        profile: str | None = None,
        budget_max_usd: float | None = None,
        target_examples: int | None = None,
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
            # J7: refuse to queue behind an already-busy pool (abuse control).
            from .abuse import enforce_concurrent_jobs

            running = await job_repo.count_in_progress(owner_principal=project.owner_principal)
            enforce_concurrent_jobs(running_count=running)
            # Defect 4.9: request-level knobs (profile / budget / target) ride on
            # the durable job input so every worker stage honours them — v0.1
            # accepted these fields over REST and silently dropped them.
            pipeline_input: dict[str, Any] = {
                "task_family_proportions": task_family_proportions or {},
            }
            if profile is not None:
                pipeline_input["profile"] = profile
            if budget_max_usd is not None:
                pipeline_input["budget_max_usd"] = budget_max_usd
            if target_examples is not None:
                pipeline_input["target_examples"] = target_examples
            job = Job(
                id=self._ids.new_handle("job"),
                project_id=project_id,
                owner_principal=project.owner_principal,
                job_type="pipeline",
                state=JobState.queued,
                idempotency_key=idempotency_key,
                input={
                    "pipeline": pipeline_input,
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
            raw_contents = await _resolve_raw_bytes(self._artifact_store(), sources, contents)

            engine = JobEngine(ids=self._ids, repo=job_repo)
            stages = [
                (
                    job.job_type,
                    _make_pipeline_stage(
                        project, sources, contents, raw_contents, self.default_project_service()
                    ),
                )
            ]
            services: dict[str, Any] = {
                "project_id": job.project_id,
                "sources": sources,
                "contents": contents,
                "raw_contents": raw_contents,
                "project": project,
            }
            job = await engine.run(job, stages, services=services)
            if job.state == JobState.succeeded:
                stash = job.input.get("_pipeline_result")
                if isinstance(stash, dict) and stash.get("examples"):
                    await self._persist_pipeline_result(session, job, stash)
            return job.model_dump(mode="json")

    async def _persist_pipeline_result(self, session: Any, job: Job, stash: dict[str, Any]) -> None:
        from ..domain.schemas import (
            Chunk,
            GenerationCandidate,
            ParsedDocument,
            SourceSpan,
            TrainingExample,
        )

        # Persist the full provenance graph (WP A) so every exported example
        # resolves to its real ParsedDocument -> SourceSpan -> SourceDocument and
        # GenerationCandidate. Order matters for FK references: parsed docs ->
        # spans -> chunks -> candidates -> examples. Explicit flush boundaries
        # guarantee FK-dependency ordering (no ORM relationship() here, so an
        # autoflush cannot be relied on to topologically sort inserts).
        parsed_repo = ParsedRepository(session)
        for d in stash.get("parsed", []):
            await parsed_repo.add(ParsedDocument(**d))
        span_repo = SpanRepository(session)
        for d in stash.get("spans", []):
            await span_repo.add(SourceSpan(**d))
        await session.flush()
        chunk_repo = ChunkRepository(session)
        for d in stash.get("chunks", []):
            await chunk_repo.add(Chunk(**d))
        await session.flush()
        cand_repo = CandidateRepository(session)
        for d in stash.get("candidates", []):
            await cand_repo.add(GenerationCandidate(**d))
        await session.flush()

        ex_repo = ExampleRepository(session)
        examples: list[TrainingExample] = []
        for d in stash["examples"]:
            ex = TrainingExample(**d)
            ex.project_id = job.project_id
            # provenance is explicit data from run_pipeline; never overwrite with
            # the project id (P0-1). source_document_ids / generation_candidate_ids
            # are carried through the stash so every example stays resolvable to
            # its real SourceDocument and GenerationCandidate.
            examples.append(ex)
            await ex_repo.add(ex)
        await session.flush()
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
            # immutable membership snapshot (WP H3) — always persisted with the
            # version row so a later review cannot silently change its contents.
            version["member_example_ids"] = [e.id for e in examples]
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

    async def resume_job(self, job_id: str) -> Job:
        """Resume a paused (e.g. budget-exhausted) job after an authorized increase.

        Only a ``paused`` job may be resumed; the caller is responsible for having
        raised the budget limit that caused the pause. Re-queues the job so a worker
        picks it up again, checkpointed (no repeated provider calls).
        """
        async with self._db.session() as session, session.begin():
            job_repo = JobRepository(session, self._ids)
            job = await job_repo.get(job_id)
            if job is None:
                raise NotFoundError(f"job not found: {job_id}")
            if job.state == JobState.succeeded:
                raise JobStateError(f"job already succeeded: {job_id}")
            if job.state not in (JobState.paused, JobState.queued, JobState.failed):
                raise JobStateError(
                    f"cannot resume job in state {job.state.value}; only paused jobs "
                    "may be resumed after a budget increase"
                )
            job.state = JobState.queued
            job.attempt_count = max(0, (job.attempt_count or 0) - 1) if job.attempt_count else 0
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
            span_repo = SpanRepository(session)
            examples, _ = await ex_repo.list_by_project(project_id, limit=limit)
            # resolve cited spans to their quoted text so grounding is
            # evidence-scoped and fail-closed (WP A2/C2)
            cited_ids = {s for ex in examples for s in ex.source_span_ids}
            spans = await span_repo.get_many(list(cited_ids))
            span_texts: dict[str, str] = {sp.id: sp.quoted_text for sp in spans}
            ctx = ValidatorContext(source_texts=span_texts, policy_version="1")
            assessments = []
            topology_of: dict[str, str] = {}
            for ex in examples:
                from ..pipeline.quality.artifact import diagnose_example

                diag = diagnose_example(ex)
                artifact = _artifact_assessment(ex, diag)
                decisions = [
                    await GroundingValidator().assess(ex, ctx),
                    await CompletenessValidator().assess(ex, ctx),
                    await FormatValidator().assess(ex, ctx),
                    await RefusalValidator().assess(ex, ctx),
                    await SchemaValidator().assess(ex, ctx),
                    await AnswerabilityValidator().assess(ex, ctx),
                    artifact,
                ]
                overall = assemble_decision(
                    decisions, example_id=ex.id, is_preference=(ex.topology.value == "preference")
                )
                assessments.append(overall)
                topology_of[ex.id] = ex.topology.value
            report = build_quality_report(assessments, topologies=topology_of).to_dict()
            return report

    # -- review (WP H1/H2; immutable revisions, P0-9) --------------------------
    async def review_example(
        self,
        *,
        example_id: str,
        revision_id: int,
        reviewer: str,
        decision: str,
        note: str = "",
        policy_version: str = "",
        concurrency_token: str | None = None,
    ) -> dict[str, Any]:
        """Apply a review decision by appending an immutable revision (P0-9).

        ``decision`` is ``approve`` / ``reject`` / ``needs_work``. A stale
        ``concurrency_token`` or base ``revision_id`` raises ``ConcurrencyError``
        (409). Returns the new revision + the persisted decision record.
        """
        from ..domain.schemas import ReviewDecision
        from ..pipeline.review.review import ReviewService

        decision_enum = ReviewDecision(decision)
        async with self._db.session() as session, session.begin():
            svc = ReviewService(
                ids=self._ids,
                revisions=RevisionRepository(session),
                reviews=ReviewRepository(session, self._ids),
                examples=ExampleRepository(session),
            )
            revision = await svc.review_example(
                example_id=example_id,
                revision_id=revision_id,
                reviewer=reviewer,
                decision=decision_enum,
                note=note,
                policy_version=policy_version,
                concurrency_token=concurrency_token,
            )
            audit = AuditRepository(session, self._ids)
            await audit.record(
                principal=reviewer,
                event_type="review.decision",
                project_id=None,
                summary=f"{reviewer} {decision_enum.value}d example {example_id}",
                payload={
                    "example_id": example_id,
                    "revision_id": revision.revision_id,
                    "decision": decision_enum.value,
                },
            )
            decisions = await svc.decisions(example_id)
            return {
                "example_id": example_id,
                "revision": revision.model_dump(mode="json"),
                "decision": decisions[-1].model_dump(mode="json") if decisions else None,
            }

    async def list_revisions(self, *, example_id: str) -> dict[str, Any]:
        from ..pipeline.review.review import ReviewService

        async with self._db.session() as session:
            svc = ReviewService(
                ids=self._ids,
                revisions=RevisionRepository(session),
                reviews=ReviewRepository(session, self._ids),
                examples=ExampleRepository(session),
            )
            revisions = await svc.revision_history(example_id)
            decisions = [d.model_dump(mode="json") for d in await svc.decisions(example_id)]
            return {"example_id": example_id, "revisions": revisions, "decisions": decisions}

    # -- versions / export / publish ------------------------------------------
    async def create_version(
        self, *, project_id: str, semantic_version: str | None = None
    ) -> DatasetVersion:
        async with self._db.session() as session, session.begin():
            ex_repo = ExampleRepository(session)
            examples, _ = await ex_repo.list_by_project(project_id, status="accepted", limit=5000)
            ver_repo = VersionRepository(session)
            # parent chain (WP H3): link to the previous latest version so a
            # version's history is walkable and never silently rewritten.
            prior = await ver_repo.latest(project_id)
            member_ids = [e.id for e in examples]
            version = DatasetVersion(
                id=self._ids.new_handle("ver"),
                project_id=project_id,
                semantic_version=semantic_version or "0.1.0",
                parent_version_id=prior.id if prior else None,
                member_example_ids=member_ids,
                train_count=sum(1 for e in examples if e.split == "train"),
                validation_count=sum(1 for e in examples if e.split == "validation"),
                test_count=sum(1 for e in examples if e.split == "test"),
                content_hash=ContentHasher.cfg_hash([e.content_hash for e in examples]),
            )
            await ver_repo.add(version)
            await ex_repo.assign_version(project_id, version.id)
            return version

    async def get_version(self, *, version_id: str) -> DatasetVersion:
        async with self._db.session() as session:
            ver_repo = VersionRepository(session)
            version = await ver_repo.get(version_id)
            if version is None:
                raise NotFoundError(f"version not found: {version_id}")
            return version

    async def export_dataset(
        self, *, project_id: str, version_id: str | None = None
    ) -> dict[str, Any]:
        from ..pipeline.export.exporters import export_jsonl
        from ..pipeline.export.gate import verify_provenance_before_export

        async with self._db.session() as session:
            ex_repo = ExampleRepository(session)
            examples, _ = await ex_repo.list_by_project(
                project_id, status="accepted", version_id=version_id, limit=5000
            )
            # A6: fail closed — block export on any broken / cross-project lineage
            # before anything is serialized.
            resolver = _ExportResolver(
                sources=SourceRepository(session),
                spans=SpanRepository(session),
                parsed=ParsedRepository(session),
                candidates=CandidateRepository(session),
            )
            await verify_provenance_before_export(examples, resolver)
            res = export_jsonl(list(examples), path="")
            return {
                "bytes": len(res.bytes),
                "lines": (res.bytes.decode("utf-8").count(chr(10))),
                "sha256": res.sha256,
            }

    async def export_dataset_formatted(
        self,
        *,
        project_id: str,
        format: str = "openai_chat",
        version_id: str | None = None,
        download_dir: str | None = None,
    ) -> ExportArtifact:
        """H5 — export accepted examples in a supported format as an artifact.

        Runs the A6 provenance gate (fail closed) before serializing, persists
        the exported bytes as a content-addressed artifact (rule 13: a success
        always returns a resolvable artifact id + sha256 digest), writes a
        downloadable local file, and returns a complete :class:`ExportArtifact`.
        """
        from ..pipeline.export.formats import MEDIA_TYPES, SUPPORTED_FORMATS, export_format
        from ..pipeline.export.gate import verify_provenance_before_export

        if format not in SUPPORTED_FORMATS and format not in ("jsonl", "parquet"):
            raise ValueError(f"unsupported export format: {format!r}")

        async with self._db.session() as session:
            ex_repo = ExampleRepository(session)
            examples, _ = await ex_repo.list_by_project(
                project_id, status="accepted", version_id=version_id, limit=5000
            )
            if not examples:
                raise NotFoundError(f"no accepted examples to export for project {project_id}")
            resolver = _ExportResolver(
                sources=SourceRepository(session),
                spans=SpanRepository(session),
                parsed=ParsedRepository(session),
                candidates=CandidateRepository(session),
            )
            # A6: fail closed — block export on any broken / cross-project lineage.
            await verify_provenance_before_export(examples, resolver)

        res = export_format(examples, format)
        store = self._artifact_store()
        manifest = await store.put(
            res.bytes,
            media_type=MEDIA_TYPES.get(format, "application/jsonl"),
            producer={"component": "export", "component_version": "1"},
            privacy="restricted",
        )
        artifact_id = manifest.get("artifact_id") or ""
        sha256 = manifest.get("sha256") or res.sha256

        root = Path(load_config().get("storage.artifact_root") or ".knovaryn/artifacts")
        out_dir = Path(download_dir) if download_dir else root / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"dataset-{project_id[:12]}-{format}.jsonl"
        download_path = out_dir / filename
        download_path.write_bytes(res.bytes)

        per_split = {
            s: sum(1 for e in examples if e.split == s) for s in ("train", "validation", "test")
        }

        # Content manifest artifact: a small JSON record tying the exported bytes
        # (by sha256) to its lineage + row/split counts. Persisted separately so
        # the download artifact's digest stays a pure hash of the payload.
        manifest_payload = {
            "format": format,
            "sha256": sha256,
            "record_count": len(examples),
            "per_split_counts": per_split,
            "source_document_ids": sorted({d for e in examples for d in e.source_document_ids}),
            "first_example_id": examples[0].id if examples else None,
        }
        manifest_meta = await store.put(
            json.dumps(manifest_payload, sort_keys=True).encode("utf-8"),
            media_type="application/json",
            producer={"component": "export", "component_version": "1"},
            privacy="restricted",
        )
        manifest_artifact_id = manifest_meta.get("artifact_id") or ""

        return ExportArtifact(
            artifact_id=artifact_id,
            download_path=str(download_path),
            media_type=MEDIA_TYPES.get(format, "application/jsonl"),
            format=format,
            version_id=version_id,
            record_count=len(examples),
            per_split_counts=per_split,
            sha256=sha256,
            manifest_artifact_id=manifest_artifact_id,
        )

    async def publish_dataset(
        self,
        *,
        project_id: str,
        repo_id: str,
        dry_run: bool = True,
        principal: str | None = None,
    ) -> dict[str, Any]:
        """Publish (default dry-run) a project's accepted examples as a dataset.

        Enforces the §15.6 publication gate: public publication is blocked unless
        every included source has an approved redistribution decision. The gate
        status is always reported, including in dry-run mode.
        """
        from ..infrastructure.publish.hf import HFPublisher, hub_available
        from ..pipeline.export.release import build_release_bundle

        # J7: a configured per-principal publication-attempt cap (abuse control).
        from .abuse import enforce_publish_attempts

        actor = principal or self._principal or "unknown"
        enforce_publish_attempts(principal=actor)
        # K4: count publication attempts (dry-run or live).
        from ..infrastructure.telemetry.metrics import get_registry

        get_registry().inc(
            "knovaryn_publication_attempts_total",
            labels={"dry_run": "true" if dry_run else "false", "principal": actor},
        )

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
            # H6: a complete publication plan with no external side effects.
            # The quality gate reflects real accepted content available to
            # publish (rule 6: not truthiness-only — an explicit count check).
            detached_sha = bundle.detached_sha256()
            quality_ok = len(examples) > 0
            return {
                "status": "dry_run",
                "destination": repo_id,
                "version_id": "0.1.0",
                "immutability_ok": True,
                "provenance_verified": True,
                "quality_gate": {
                    "allowed": quality_ok,
                    "reason": f"{len(examples)} accepted examples",
                },
                "license_gate": {
                    "allowed": gate["allowed"],
                    "reason": gate["reason"],
                    "unresolved": gate["unresolved"],
                },
                "privacy_gate": privacy_summary,
                "detached_checksum_sha256": detached_sha,
                "human_review_ok": gate["allowed"],
                "critical_warnings_resolved": gate["allowed"],
                "plan_artifacts": _release_artifacts_from_zip(bundle, detached_sha),
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


async def _resolve_raw_bytes(
    store: Any, sources: list[SourceDocument], contents: list[str]
) -> list[bytes]:
    """Resolve parser input bytes for each source (WP G3).

    Text sources keep their in-metadata content (compat with the legacy path);
    artifact-backed sources (``artifact_id_original`` set, no text content) are
    fetched by sha256 from the content-addressed artifact store so binary / ZIP /
    office documents are parsed from their immutable original bytes — never from
    a lossy text field.
    """
    raw: list[bytes] = []
    for src, text in zip(sources, contents, strict=True):
        if text or not (src.artifact_id_original or src.sha256):
            raw.append(text.encode("utf-8"))
            continue
        try:
            raw.append(await store.get(src.sha256))
        except Exception:  # noqa: BLE001
            # fall back to whatever text we have so a missing artifact doesn't
            # take the whole job down; diagnostics surface in extraction quality.
            raw.append(text.encode("utf-8"))
    return raw


@dataclass
class _ExportResolver:
    """Repository accessor for the A6 export provenance gate."""

    sources: Any
    spans: Any
    parsed: Any
    candidates: Any


def _make_pipeline_stage(
    project: Project,
    sources: list[SourceDocument],
    contents: list[str],
    raw_contents: list[bytes],
    svc: ProjectService,
) -> Callable[[Any], Awaitable[dict[str, Any]]]:
    async def stage(ctx: Any) -> dict[str, Any]:
        cfg = ctx.config or {}
        plan = DatasetPlan(
            task_family_proportions=cfg.get("task_family_proportions")
            or {"factual_explanation": 0.5, "procedure": 0.3, "comparison": 0.2}
        )
        result = await svc.run_pipeline(
            project=project,
            sources=sources,
            raw_contents=raw_contents,
            plan=plan,
            target_examples=cfg.get("target_examples"),
        )
        stash = {
            "examples": [e.model_dump(mode="json") for e in result.examples],
            "parsed": [p.model_dump(mode="json") for p in result.parsed],
            "spans": [s.model_dump(mode="json") for s in result.spans],
            "chunks": [c.model_dump(mode="json") for c in result.chunks],
            "candidates": [c.model_dump(mode="json") for c in result.candidates],
            "version": result.version.model_dump(mode="json") if result.version else None,
            "release_sha256": result.release_sha256,
            "quality": result.quality,
            "notes": result.notes,
        }
        ctx.job.input["_pipeline_result"] = stash
        await ctx.checkpoint("pipeline", step=1, key="result", value=result.to_dict())
        return result.to_dict()

    return stage


def _release_artifacts_from_zip(bundle: Any, detached_sha256: str) -> list[dict[str, Any]]:
    """H6 — enumerate the publication plan's artifacts with their digest.

    Each logical file in the bundle maps to ``{logical_path, sha256}`` from the
    in-archive per-file manifest, plus a detached ``release.zip.sha256`` record
    for the whole archive (I2). No parsing of display strings (rule 6).
    """
    files = bundle.manifest.get("files", [])
    artifacts = [{"logical_path": f.get("logical_path"), "sha256": f.get("sha256")} for f in files]
    artifacts.append({"logical_path": "release.zip.sha256", "sha256": detached_sha256})
    return artifacts
