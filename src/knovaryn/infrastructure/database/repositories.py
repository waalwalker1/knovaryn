"""SQLAlchemy repositories (spec §21).

Typed repositories backing the domain ports. Each maps to AsyncSession.
Primary-key lookup by UUIDv7 string handle; never expose sequential ids.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain import schemas
from ...domain.ids import IdGenerator
from . import models as m


class ProjectRepository:
    def __init__(self, session: AsyncSession, ids: IdGenerator) -> None:
        self._s = session
        self._ids = ids

    async def create(self, project: schemas.Project) -> schemas.Project:
        row = m.ProjectDB(
            id=project.id,
            slug=project.slug,
            display_name=project.display_name,
            description=project.description,
            owner_principal=project.owner_principal,
            created_at=project.created_at,
            updated_at=project.updated_at,
            default_profile=project.default_profile,
            status=project.status,
            tags=project.tags,
        )
        self._s.add(row)
        return project

    async def get(self, project_id: str) -> schemas.Project | None:
        row = await self._s.get(m.ProjectDB, project_id)
        return _to_project(row) if row else None

    async def get_by_slug(self, slug: str) -> schemas.Project | None:
        res = await self._s.execute(select(m.ProjectDB).where(m.ProjectDB.slug == slug))
        row = res.scalar_one_or_none()
        return _to_project(row) if row else None

    async def list_(
        self, *, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[schemas.Project], str | None]:
        stmt = select(m.ProjectDB).order_by(m.ProjectDB.created_at.desc()).limit(limit + 1)
        if cursor:
            stmt = stmt.where(m.ProjectDB.id < cursor)
        rows = (await self._s.execute(stmt)).scalars().all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = rows[-1].id if has_more and rows else None
        return [_to_project(r) for r in rows], next_cursor

    async def save(self, project: schemas.Project) -> None:
        await self._s.execute(
            update(m.ProjectDB)
            .where(m.ProjectDB.id == project.id)
            .values(
                display_name=project.display_name,
                description=project.description,
                default_profile=project.default_profile,
                status=project.status,
                tags=project.tags,
                updated_at=project.updated_at,
            )
        )


def _to_project(r: m.ProjectDB) -> schemas.Project:
    return schemas.Project(
        id=r.id,
        slug=r.slug,
        display_name=r.display_name,
        description=r.description,
        owner_principal=r.owner_principal,
        created_at=r.created_at,
        updated_at=r.updated_at,
        default_profile=r.default_profile,
        status=r.status,
        tags=r.tags or [],
    )


class SourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, src: schemas.SourceDocument) -> None:
        self._s.add(
            m.SourceDocumentDB(
                id=src.id,
                project_id=src.project_id,
                original_name=src.original_name,
                media_type=src.media_type,
                byte_size=src.byte_size,
                sha256=src.sha256,
                source_kind=src.source_kind.value,
                source_locator_redacted=src.source_locator_redacted,
                acquisition_time=src.acquisition_time,
                declared_license=src.declared_license,
                detected_license=src.detected_license,
                license_status=src.license_status.value,
                privacy_classification=src.privacy_classification,
                language_candidates=src.language_candidates,
                page_or_sheet_count=src.page_or_sheet_count,
                intake_status=src.intake_status.value,
                artifact_id_original=src.artifact_id_original,
                group_key=src.group_key,
                metadata_=src.metadata,
            )
        )

    async def get(self, source_id: str) -> schemas.SourceDocument | None:
        row = await self._s.get(m.SourceDocumentDB, source_id)
        return _to_source(row) if row else None

    async def list_by_project(
        self, project_id: str, *, limit: int = 100, cursor: str | None = None
    ) -> tuple[list[schemas.SourceDocument], str | None]:
        stmt = (
            select(m.SourceDocumentDB)
            .where(m.SourceDocumentDB.project_id == project_id)
            .order_by(m.SourceDocumentDB.acquisition_time.desc())
            .limit(limit + 1)
        )
        if cursor:
            stmt = stmt.where(m.SourceDocumentDB.id < cursor)
        rows = (await self._s.execute(stmt)).scalars().all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = rows[-1].id if has_more and rows else None
        return [_to_source(r) for r in rows], next_cursor

    async def count_by_project(self, project_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(m.SourceDocumentDB)
            .where(m.SourceDocumentDB.project_id == project_id)
        )
        return int((await self._s.execute(stmt)).scalar_one())

    async def save(self, src: schemas.SourceDocument) -> None:
        await self._s.execute(
            update(m.SourceDocumentDB)
            .where(m.SourceDocumentDB.id == src.id)
            .values(
                license_status=src.license_status.value,
                privacy_classification=src.privacy_classification,
                page_or_sheet_count=src.page_or_sheet_count,
                intake_status=src.intake_status.value,
                detected_license=src.detected_license,
                language_candidates=src.language_candidates,
                group_key=src.group_key,
                metadata_=src.metadata,
            )
        )


def _to_source(r: m.SourceDocumentDB) -> schemas.SourceDocument:
    return schemas.SourceDocument(
        id=r.id,
        project_id=r.project_id,
        original_name=r.original_name,
        media_type=r.media_type,
        byte_size=r.byte_size,
        sha256=r.sha256,
        source_kind=schemas.SourceKind(r.source_kind),
        source_locator_redacted=r.source_locator_redacted,
        acquisition_time=r.acquisition_time,
        declared_license=r.declared_license,
        detected_license=r.detected_license,
        license_status=schemas.LicenseStatus(r.license_status),
        privacy_classification=r.privacy_classification,
        language_candidates=r.language_candidates or [],
        page_or_sheet_count=r.page_or_sheet_count,
        intake_status=schemas.IntakeStatus(r.intake_status),
        artifact_id_original=r.artifact_id_original,
        group_key=r.group_key,
        metadata=r.metadata_ or {},
    )


class JobRepository:
    def __init__(self, session: AsyncSession, ids: IdGenerator) -> None:
        self._s = session
        self._ids = ids

    async def create(self, job: schemas.Job) -> schemas.Job:
        self._s.add(_job_to_row(job))
        return job

    async def get(self, job_id: str) -> schemas.Job | None:
        row = await self._s.get(m.JobDB, job_id)
        return _job_from_row(row) if row else None

    async def get_by_idempotency(self, key: str) -> schemas.Job | None:
        res = await self._s.execute(select(m.JobDB).where(m.JobDB.idempotency_key == key))
        row = res.scalar_one_or_none()
        return _job_from_row(row) if row else None

    async def save(self, job: schemas.Job) -> None:
        await self._s.execute(
            update(m.JobDB)
            .where(m.JobDB.id == job.id)
            .values(
                state=job.state.value,
                current_stage=job.current_stage,
                progress_current=job.progress_current,
                progress_total=job.progress_total,
                lease_owner=job.lease_owner,
                lease_expires_at=job.lease_expires_at,
                heartbeat_at=job.heartbeat_at,
                attempt_count=job.attempt_count,
                cancellation_requested_at=job.cancellation_requested_at,
                estimated_cost=job.estimated_cost,
                actual_cost=job.actual_cost,
                started_at=job.started_at,
                finished_at=job.finished_at,
                error_code=job.error_code,
                error_summary=job.error_summary,
            )
        )

    async def claim_eligible(self, *, worker: str, lease_seconds: int = 300) -> schemas.Job | None:
        """Atomically claim one eligible queued/retry_wait job (best-effort local)."""
        from datetime import datetime, timedelta

        now = datetime.now(UTC)
        stmt = (
            select(m.JobDB)
            .where(
                m.JobDB.state.in_(["queued", "retry_wait"]),
                (m.JobDB.lease_expires_at.is_(None)) | (m.JobDB.lease_expires_at < now),
            )
            .order_by(m.JobDB.created_at)
            .limit(1)
        )
        res = await self._s.execute(stmt)
        row = res.scalars().first()
        if row is None:
            return None
        # claim (best-effort; single-worker SQLite path)
        row.state = "leased"
        row.lease_owner = worker
        row.lease_expires_at = now + timedelta(seconds=lease_seconds)
        row.heartbeat_at = now
        row.attempt_count += 1
        await self._s.flush()
        return _job_from_row(row)

    async def list_(
        self, *, project_id: str | None = None, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[schemas.Job], str | None]:
        stmt = select(m.JobDB).order_by(m.JobDB.created_at.desc()).limit(limit + 1)
        if project_id:
            stmt = stmt.where(m.JobDB.project_id == project_id)
        if cursor:
            stmt = stmt.where(m.JobDB.id < cursor)
        rows = (await self._s.execute(stmt)).scalars().all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = rows[-1].id if has_more and rows else None
        return [_job_from_row(r) for r in rows], next_cursor

    async def append_event(self, job_id: str, event: schemas.JobEvent) -> None:
        # compute sequence
        stmt = select(func.coalesce(func.max(m.JobEventDB.sequence), 0) + 1).where(
            m.JobEventDB.job_id == job_id
        )
        seq = int((await self._s.execute(stmt)).scalar_one())
        event.sequence = seq
        self._s.add(
            m.JobEventDB(
                id=event.id,
                job_id=job_id,
                sequence=seq,
                timestamp=event.timestamp,
                level=event.level,
                event_type=event.event_type,
                stage=event.stage,
                message=event.message,
                structured_payload=event.structured_payload,
            )
        )

    async def get_events(
        self, job_id: str, *, cursor: int | None = None, limit: int = 100
    ) -> tuple[list[schemas.JobEvent], int | None]:
        stmt = (
            select(m.JobEventDB)
            .where(m.JobEventDB.job_id == job_id)
            .order_by(m.JobEventDB.sequence)
            .limit(limit + 1)
        )
        if cursor is not None:
            stmt = stmt.where(m.JobEventDB.sequence > cursor)
        rows = (await self._s.execute(stmt)).scalars().all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = rows[-1].sequence if has_more and rows else None
        return [_event_from_row(r) for r in rows], next_cursor


def _job_to_row(job: schemas.Job) -> m.JobDB:
    return m.JobDB(
        id=job.id,
        project_id=job.project_id,
        owner_principal=job.owner_principal,
        job_type=job.job_type,
        state=job.state.value,
        current_stage=job.current_stage,
        progress_current=job.progress_current,
        progress_total=job.progress_total,
        idempotency_key=job.idempotency_key,
        input_config_hash=job.input_config_hash,
        lease_owner=job.lease_owner,
        lease_expires_at=job.lease_expires_at,
        heartbeat_at=job.heartbeat_at,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        cancellation_requested_at=job.cancellation_requested_at,
        estimated_cost=job.estimated_cost,
        actual_cost=job.actual_cost,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error_code=job.error_code,
        error_summary=job.error_summary,
        input=job.input,
    )


def _job_from_row(r: m.JobDB) -> schemas.Job:
    return schemas.Job(
        id=r.id,
        project_id=r.project_id,
        owner_principal=r.owner_principal,
        job_type=r.job_type,
        state=schemas.JobState(r.state),
        current_stage=r.current_stage,
        progress_current=r.progress_current,
        progress_total=r.progress_total,
        idempotency_key=r.idempotency_key,
        input_config_hash=r.input_config_hash,
        lease_owner=r.lease_owner,
        lease_expires_at=r.lease_expires_at,
        heartbeat_at=r.heartbeat_at,
        attempt_count=r.attempt_count,
        max_attempts=r.max_attempts,
        cancellation_requested_at=r.cancellation_requested_at,
        estimated_cost=r.estimated_cost,
        actual_cost=r.actual_cost,
        created_at=r.created_at,
        started_at=r.started_at,
        finished_at=r.finished_at,
        error_code=r.error_code,
        error_summary=r.error_summary,
        input=r.input or {},
    )


def _event_from_row(r: m.JobEventDB) -> schemas.JobEvent:
    return schemas.JobEvent(
        id=r.id,
        job_id=r.job_id,
        sequence=r.sequence,
        timestamp=r.timestamp,
        level=r.level,
        event_type=r.event_type,
        stage=r.stage,
        message=r.message,
        structured_payload=r.structured_payload or {},
    )


class ExampleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, ex: schemas.TrainingExample) -> None:
        self._s.add(_example_to_row(ex))

    async def get(self, example_id: str) -> schemas.TrainingExample | None:
        row = await self._s.get(m.TrainingExampleDB, example_id)
        return _example_from_row(row) if row else None

    async def list_by_project(
        self,
        project_id: str,
        *,
        status: str | None = None,
        version_id: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[schemas.TrainingExample], str | None]:
        stmt = select(m.TrainingExampleDB).where(m.TrainingExampleDB.project_id == project_id)
        if status:
            stmt = stmt.where(m.TrainingExampleDB.quality_status == status)
        if version_id:
            stmt = stmt.where(m.TrainingExampleDB.version_id == version_id)
        stmt = stmt.order_by(m.TrainingExampleDB.created_at.desc()).limit(limit + 1)
        if cursor:
            stmt = stmt.where(m.TrainingExampleDB.id < cursor)
        rows = (await self._s.execute(stmt)).scalars().all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = rows[-1].id if has_more and rows else None
        return [_example_from_row(r) for r in rows], next_cursor

    async def count_accepted_by_project(
        self, project_id: str, *, version_id: str | None = None
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(m.TrainingExampleDB)
            .where(
                m.TrainingExampleDB.project_id == project_id,
                m.TrainingExampleDB.quality_status == "accepted",
            )
        )
        if version_id:
            stmt = stmt.where(m.TrainingExampleDB.version_id == version_id)
        return int((await self._s.execute(stmt)).scalar_one())

    async def assign_version(self, project_id: str, version_id: str) -> None:
        await self._s.execute(
            update(m.TrainingExampleDB)
            .where(
                m.TrainingExampleDB.project_id == project_id,
                m.TrainingExampleDB.quality_status == "accepted",
            )
            .values(version_id=version_id)
        )

    async def replace_existing(self, ex: schemas.TrainingExample) -> None:
        """Insert or update by id (used by validators writing assessments)."""
        await self._s.merge(_example_to_row(ex))

    async def count(self, *, where: tuple[Any, ...] = ()) -> int:
        stmt = select(func.count()).select_from(m.TrainingExampleDB)
        for cond in where:
            stmt = stmt.where(cond)
        return int((await self._s.execute(stmt)).scalar_one())


def _example_to_row(ex: schemas.TrainingExample) -> m.TrainingExampleDB:
    return m.TrainingExampleDB(
        id=ex.id,
        project_id=ex.project_id,
        topology=ex.topology.value,
        system_messages=ex.system_messages,
        prompt_messages=[mdl.model_dump(mode="json") for mdl in ex.prompt_messages],
        chosen_messages=[mdl.model_dump(mode="json") for mdl in ex.chosen_messages],
        rejected_messages=[mdl.model_dump(mode="json") for mdl in ex.rejected_messages],
        label_or_target=ex.label_or_target,
        source_span_ids=ex.source_span_ids,
        source_document_ids=ex.source_document_ids,
        generation_candidate_ids=ex.generation_candidate_ids,
        quality_status=ex.quality_status.value,
        quality_score=ex.quality_score,
        quality_dimensions=ex.quality_dimensions,
        defect_taxonomy=ex.defect_taxonomy,
        trainer_visible_metadata=ex.trainer_visible_metadata,
        private_audit_metadata=ex.private_audit_metadata,
        content_hash=ex.content_hash,
        split=ex.split,
        version_id=None,
        created_at=ex.created_at,
    )


def _example_from_row(r: m.TrainingExampleDB) -> schemas.TrainingExample:
    return schemas.TrainingExample(
        id=r.id,
        project_id=r.project_id,
        topology=schemas.Topology(r.topology),
        system_messages=r.system_messages or [],
        prompt_messages=[schemas.CanonicalMessage(**x) for x in (r.prompt_messages or [])],
        chosen_messages=[schemas.CanonicalMessage(**x) for x in (r.chosen_messages or [])],
        rejected_messages=[schemas.CanonicalMessage(**x) for x in (r.rejected_messages or [])],
        label_or_target=r.label_or_target,
        source_span_ids=r.source_span_ids or [],
        source_document_ids=r.source_document_ids or [],
        generation_candidate_ids=r.generation_candidate_ids or [],
        quality_status=schemas.QualityStatus(r.quality_status),
        quality_score=r.quality_score,
        quality_dimensions=r.quality_dimensions or {},
        defect_taxonomy=r.defect_taxonomy or [],
        trainer_visible_metadata=r.trainer_visible_metadata or {},
        private_audit_metadata=r.private_audit_metadata or {},
        content_hash=r.content_hash,
        split=r.split,
        created_at=r.created_at,
    )


class VersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, v: schemas.DatasetVersion) -> None:
        self._s.add(
            m.DatasetVersionDB(
                id=v.id,
                project_id=v.project_id,
                semantic_version=v.semantic_version,
                parent_version_id=v.parent_version_id,
                manifest_artifact_id=v.manifest_artifact_id,
                quality_report_artifact_id=v.quality_report_artifact_id,
                dataset_card_artifact_id=v.dataset_card_artifact_id,
                source_manifest_artifact_id=v.source_manifest_artifact_id,
                license_report_artifact_id=v.license_report_artifact_id,
                privacy_report_artifact_id=v.privacy_report_artifact_id,
                train_count=v.train_count,
                validation_count=v.validation_count,
                test_count=v.test_count,
                content_hash=v.content_hash,
                created_at=v.created_at,
                release_status=v.release_status.value,
            )
        )

    async def get(self, version_id: str) -> schemas.DatasetVersion | None:
        row = await self._s.get(m.DatasetVersionDB, version_id)
        return _version_from_row(row) if row else None

    async def latest(self, project_id: str) -> schemas.DatasetVersion | None:
        res = await self._s.execute(
            select(m.DatasetVersionDB)
            .where(m.DatasetVersionDB.project_id == project_id)
            .order_by(m.DatasetVersionDB.created_at.desc())
            .limit(1)
        )
        row = res.scalar_one_or_none()
        return _version_from_row(row) if row else None

    async def save(self, v: schemas.DatasetVersion) -> None:
        await self._s.execute(
            update(m.DatasetVersionDB)
            .where(m.DatasetVersionDB.id == v.id)
            .values(
                release_status=v.release_status.value,
                manifest_artifact_id=v.manifest_artifact_id,
                quality_report_artifact_id=v.quality_report_artifact_id,
                dataset_card_artifact_id=v.dataset_card_artifact_id,
                source_manifest_artifact_id=v.source_manifest_artifact_id,
                license_report_artifact_id=v.license_report_artifact_id,
                privacy_report_artifact_id=v.privacy_report_artifact_id,
            )
        )


def _version_from_row(r: m.DatasetVersionDB) -> schemas.DatasetVersion:
    return schemas.DatasetVersion(
        id=r.id,
        project_id=r.project_id,
        semantic_version=r.semantic_version,
        parent_version_id=r.parent_version_id,
        manifest_artifact_id=r.manifest_artifact_id,
        quality_report_artifact_id=r.quality_report_artifact_id,
        dataset_card_artifact_id=r.dataset_card_artifact_id,
        source_manifest_artifact_id=r.source_manifest_artifact_id,
        license_report_artifact_id=r.license_report_artifact_id,
        privacy_report_artifact_id=r.privacy_report_artifact_id,
        train_count=r.train_count,
        validation_count=r.validation_count,
        test_count=r.test_count,
        content_hash=r.content_hash,
        created_at=r.created_at,
        release_status=schemas.ReleaseStatus(r.release_status),
    )


class CostLedgerRepository:
    def __init__(self, session: AsyncSession, ids: IdGenerator) -> None:
        self._s = session
        self._ids = ids

    async def record(self, entry: dict[str, Any]) -> None:
        self._s.add(
            m.CostLedgerDB(
                id=self._ids.new(),
                job_id=entry.get("job_id"),
                project_id=entry.get("project_id"),
                stage=entry.get("stage", ""),
                provider=entry.get("provider", ""),
                model=entry.get("model", ""),
                input_tokens=entry.get("input_tokens", 0),
                cached_input_tokens=entry.get("cached_input_tokens", 0),
                output_tokens=entry.get("output_tokens", 0),
                provider_request_id=entry.get("provider_request_id"),
                latency_ms=entry.get("latency_ms", 0),
                retries=entry.get("retries", 0),
                price_snapshot_date=entry.get("price_snapshot_date"),
                price_input_per_m=entry.get("price_input_per_m", 0.0),
                price_output_per_m=entry.get("price_output_per_m", 0.0),
                estimated_cost=entry.get("estimated_cost", 0.0),
            )
        )

    async def sum_by_job(self, job_id: str) -> float:
        stmt = select(func.coalesce(func.sum(m.CostLedgerDB.estimated_cost), 0.0)).where(
            m.CostLedgerDB.job_id == job_id
        )
        return float((await self._s.execute(stmt)).scalar_one())


class AuditRepository:
    def __init__(self, session: AsyncSession, ids: IdGenerator) -> None:
        self._s = session
        self._ids = ids

    async def record(
        self,
        *,
        principal: str,
        event_type: str,
        project_id: str | None,
        summary: str,
        payload: dict[str, Any],
    ) -> None:
        self._s.add(
            m.AuditEventDB(
                id=self._ids.new(),
                principal=principal,
                event_type=event_type,
                project_id=project_id,
                summary=summary,
                payload=payload,
            )
        )


class ParsedRepository:
    """Persist/query parsed documents (WP A1/A3)."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, p: schemas.ParsedDocument) -> None:
        self._s.add(
            m.ParsedDocumentDB(
                id=p.id,
                source_document_id=p.source_document_id,
                parser_name=p.parser_name,
                parser_version=p.parser_version,
                parser_config_hash=p.parser_config_hash,
                canonical_docling_json_artifact_id=p.canonical_docling_json_artifact_id,
                markdown_artifact_id=p.markdown_artifact_id,
                text_artifact_id=p.text_artifact_id,
                diagnostics_artifact_id=p.diagnostics_artifact_id,
                extraction_status=p.extraction_status.value
                if isinstance(p.extraction_status, schemas.ExtractionStatus)
                else p.extraction_status,
                extraction_quality_summary=p.extraction_quality_summary,
                created_at=p.created_at,
            )
        )

    async def get(self, parsed_id: str) -> schemas.ParsedDocument | None:
        row = await self._s.get(m.ParsedDocumentDB, parsed_id)
        if row is None:
            return None
        return schemas.ParsedDocument(
            id=row.id,
            source_document_id=row.source_document_id,
            parser_name=row.parser_name,
            parser_version=row.parser_version,
            parser_config_hash=row.parser_config_hash,
            canonical_docling_json_artifact_id=row.canonical_docling_json_artifact_id,
            markdown_artifact_id=row.markdown_artifact_id,
            text_artifact_id=row.text_artifact_id,
            diagnostics_artifact_id=row.diagnostics_artifact_id,
            extraction_status=schemas.ExtractionStatus(row.extraction_status),
            extraction_quality_summary=row.extraction_quality_summary or {},
            created_at=row.created_at,
        )

    async def list_by_source(self, source_document_id: str) -> list[schemas.ParsedDocument]:
        res = await self._s.execute(
            select(m.ParsedDocumentDB).where(
                m.ParsedDocumentDB.source_document_id == source_document_id
            )
        )
        rows = [await self.get(r.id) for r in res.scalars().all() if r]
        return [x for x in rows if x is not None]


class SpanRepository:
    """Persist/query source spans (WP A2)."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, span: schemas.SourceSpan) -> None:
        self._s.add(
            m.SourceSpanDB(
                id=span.id,
                parsed_document_id=span.parsed_document_id,
                page_number=span.page_number,
                section_path=span.section_path,
                element_reference=span.element_reference,
                character_start=span.character_start,
                character_end=span.character_end,
                quoted_text=span.quoted_text,
                sha256=span.sha256,
            )
        )

    async def get(self, span_id: str) -> schemas.SourceSpan | None:
        row = await self._s.get(m.SourceSpanDB, span_id)
        if row is None:
            return None
        return schemas.SourceSpan(
            id=row.id,
            parsed_document_id=row.parsed_document_id,
            page_number=row.page_number,
            section_path=row.section_path,
            element_reference=row.element_reference,
            character_start=row.character_start,
            character_end=row.character_end,
            quoted_text=row.quoted_text,
            sha256=row.sha256,
        )

    async def list_by_parsed(self, parsed_document_id: str) -> list[schemas.SourceSpan]:
        res = await self._s.execute(
            select(m.SourceSpanDB).where(m.SourceSpanDB.parsed_document_id == parsed_document_id)
        )
        rows = [await self.get(r.id) for r in res.scalars().all() if r]
        return [x for x in rows if x is not None]

    async def get_many(self, span_ids: list[str]) -> list[schemas.SourceSpan]:
        if not span_ids:
            return []
        res = await self._s.execute(
            select(m.SourceSpanDB).where(m.SourceSpanDB.id.in_(span_ids))
        )
        rows = [await self.get(r.id) for r in res.scalars().all() if r]
        return [x for x in rows if x is not None]


class ChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, chunk: schemas.Chunk) -> None:
        self._s.add(
            m.ChunkDB(
                id=chunk.id,
                parsed_document_id=chunk.parsed_document_id,
                source_document_id=chunk.source_document_id,
                source_group_id=chunk.source_group_id,
                split_group_id=chunk.split_group_id,
                ordinal=chunk.ordinal,
                heading_path=chunk.heading_path,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                structural_type=chunk.structural_type,
                main_text=chunk.main_text,
                rendered_context=chunk.rendered_context,
                token_count=chunk.token_count,
                source_span_ids=chunk.source_span_ids,
                chunker_name=chunk.chunker_name,
                chunker_version=chunk.chunker_version,
                chunker_config_hash=chunk.chunker_config_hash,
                sha256=chunk.sha256,
                metadata_=chunk.metadata,
            )
        )

    async def get(self, chunk_id: str) -> schemas.Chunk | None:
        row = await self._s.get(m.ChunkDB, chunk_id)
        if row is None:
            return None
        return schemas.Chunk(
            id=row.id,
            parsed_document_id=row.parsed_document_id,
            source_document_id=row.source_document_id or "",
            source_group_id=row.source_group_id,
            split_group_id=row.split_group_id,
            ordinal=row.ordinal,
            heading_path=row.heading_path or [],
            page_start=row.page_start,
            page_end=row.page_end,
            structural_type=row.structural_type,
            main_text=row.main_text,
            rendered_context=row.rendered_context,
            token_count=row.token_count,
            source_span_ids=row.source_span_ids or [],
            chunker_name=row.chunker_name,
            chunker_version=row.chunker_version,
            chunker_config_hash=row.chunker_config_hash,
            sha256=row.sha256,
            metadata=row.metadata_ or {},
        )


class CandidateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, cand: schemas.GenerationCandidate) -> None:
        self._s.add(
            m.GenerationCandidateDB(
                id=cand.id,
                project_id=cand.project_id,
                chunk_id=cand.chunk_id,
                source_document_id=cand.source_document_id,
                source_group_id=cand.source_group_id,
                split=cand.split,
                source_span_ids=cand.source_span_ids,
                topology=cand.topology,
                task_family=cand.task_family,
                prompt_template_name=cand.prompt_template_name,
                prompt_template_version=cand.prompt_template_version,
                prompt_template_hash=cand.prompt_template_hash,
                schema_hash=cand.schema_hash,
                provider=cand.provider,
                model=cand.model,
                profile=cand.profile,
                call_fingerprint=cand.call_fingerprint,
                raw_output_artifact_id=cand.raw_output_artifact_id,
                candidate_hash=cand.candidate_hash,
                status=cand.status,
                created_at=cand.created_at,
                metadata_=cand.metadata,
            )
        )

    async def get(self, candidate_id: str) -> schemas.GenerationCandidate | None:
        row = await self._s.get(m.GenerationCandidateDB, candidate_id)
        if row is None:
            return None
        return schemas.GenerationCandidate(
            id=row.id,
            project_id=row.project_id,
            chunk_id=row.chunk_id,
            source_document_id=row.source_document_id,
            source_group_id=row.source_group_id,
            split=row.split,
            source_span_ids=row.source_span_ids or [],
            topology=row.topology,
            task_family=row.task_family,
            prompt_template_name=row.prompt_template_name,
            prompt_template_version=row.prompt_template_version,
            prompt_template_hash=row.prompt_template_hash,
            schema_hash=row.schema_hash,
            provider=row.provider,
            model=row.model,
            profile=row.profile,
            call_fingerprint=row.call_fingerprint,
            raw_output_artifact_id=row.raw_output_artifact_id,
            candidate_hash=row.candidate_hash,
            status=row.status,
            created_at=row.created_at,
            metadata=row.metadata_ or {},
        )

    async def get_many(self, candidate_ids: list[str]) -> list[schemas.GenerationCandidate]:
        if not candidate_ids:
            return []
        res = await self._s.execute(
            select(m.GenerationCandidateDB).where(m.GenerationCandidateDB.id.in_(candidate_ids))
        )
        rows = [await self.get(r.id) for r in res.scalars().all() if r]
        return [x for x in rows if x is not None]


class ModelCallRepository:
    def __init__(self, session: AsyncSession, ids: IdGenerator) -> None:
        self._s = session
        self._ids = ids

    async def record(self, call: dict[str, Any]) -> None:
        self._s.add(
            m.ModelCallDB(
                id=self._ids.new(),
                job_id=call.get("job_id"),
                project_id=call.get("project_id", ""),
                stage=call.get("stage", ""),
                provider=call.get("provider", ""),
                requested_model=call.get("requested_model", ""),
                resolved_model=call.get("resolved_model", ""),
                profile=call.get("profile", ""),
                prompt_template_hash=call.get("prompt_template_hash", ""),
                request_fingerprint=call.get("request_fingerprint", ""),
                schema_hash=call.get("schema_hash", ""),
                sampling_params=call.get("sampling_params", {}),
                input_tokens=call.get("input_tokens", 0),
                cached_input_tokens=call.get("cached_input_tokens", 0),
                output_tokens=call.get("output_tokens", 0),
                estimated_cost=call.get("estimated_cost", 0.0),
                provider_request_id=call.get("provider_request_id"),
                latency_ms=call.get("latency_ms", 0),
                retry_count=call.get("retry_count", 0),
                result_artifact_id=call.get("result_artifact_id"),
                status=call.get("status", "ok"),
            )
        )

    async def get_by_fingerprint(self, job_id: str, fingerprint: str) -> Any:
        res = await self._s.execute(
            select(m.ModelCallDB).where(
                m.ModelCallDB.job_id == job_id,
                m.ModelCallDB.request_fingerprint == fingerprint,
            )
        )
        return res.scalars().first()
