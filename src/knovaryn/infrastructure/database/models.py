"""SQLAlchemy 2.x async ORM models (spec §21.1).

Typed mappings mirroring the domain entities. Every row references committed
artifact IDs (sha256 / manifest handles). No framework logic here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class ProjectDB(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    owner_principal: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    default_profile: Mapped[str] = mapped_column(String(64), default="balanced")
    status: Mapped[str] = mapped_column(String(32), default="active")
    tags: Mapped[list] = mapped_column(JSON, default=list)

    sources: Mapped[list[SourceDocumentDB]] = relationship(back_populates="project")


class SourceDocumentDB(Base):
    __tablename__ = "source_documents"
    __table_args__ = (Index("ix_source_project", "project_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    original_name: Mapped[str] = mapped_column(String(1024))
    media_type: Mapped[str] = mapped_column(String(255))
    byte_size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    source_kind: Mapped[str] = mapped_column(String(32), default="upload")
    source_locator_redacted: Mapped[str] = mapped_column(String(1024), default="")
    acquisition_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    declared_license: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detected_license: Mapped[str | None] = mapped_column(String(255), nullable=True)
    license_status: Mapped[str] = mapped_column(String(32), default="unknown")
    privacy_classification: Mapped[str] = mapped_column(String(64), default="unknown")
    language_candidates: Mapped[list] = mapped_column(JSON, default=list)
    page_or_sheet_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    intake_status: Mapped[str] = mapped_column(String(32), default="pending")
    artifact_id_original: Mapped[str | None] = mapped_column(String(64), nullable=True)
    group_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    project: Mapped[ProjectDB] = relationship(back_populates="sources")


class ParsedDocumentDB(Base):
    __tablename__ = "parsed_documents"
    __table_args__ = (Index("ix_parsed_source", "source_document_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), index=True)
    parser_name: Mapped[str] = mapped_column(String(128))
    parser_version: Mapped[str] = mapped_column(String(64))
    parser_config_hash: Mapped[str] = mapped_column(String(64))
    canonical_docling_json_artifact_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    markdown_artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    text_artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    diagnostics_artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extraction_status: Mapped[str] = mapped_column(String(32), default="pending")
    extraction_quality_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChunkDB(Base):
    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunk_parsed", "parsed_document_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    parsed_document_id: Mapped[str] = mapped_column(ForeignKey("parsed_documents.id"), index=True)
    source_document_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    source_group_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    split_group_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    heading_path: Mapped[list] = mapped_column(JSON, default=list)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    structural_type: Mapped[str] = mapped_column(String(64), default="text")
    main_text: Mapped[str] = mapped_column(Text, default="")
    rendered_context: Mapped[str] = mapped_column(Text, default="")
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    source_span_ids: Mapped[list] = mapped_column(JSON, default=list)
    chunker_name: Mapped[str] = mapped_column(String(128))
    chunker_version: Mapped[str] = mapped_column(String(64))
    chunker_config_hash: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class SourceSpanDB(Base):
    __tablename__ = "source_spans"
    __table_args__ = (Index("ix_span_parsed", "parsed_document_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    parsed_document_id: Mapped[str] = mapped_column(ForeignKey("parsed_documents.id"), index=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_path: Mapped[str] = mapped_column(String(1024), default="")
    element_reference: Mapped[str] = mapped_column(String(255), default="")
    character_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    character_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quoted_text: Mapped[str] = mapped_column(Text, default="")
    sha256: Mapped[str] = mapped_column(String(64))


class TrainingExampleDB(Base):
    __tablename__ = "training_examples"
    __table_args__ = (
        Index("ix_example_project", "project_id"),
        Index("ix_example_status", "quality_status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    topology: Mapped[str] = mapped_column(String(32), default="sft")
    system_messages: Mapped[list] = mapped_column(JSON, default=list)
    prompt_messages: Mapped[list] = mapped_column(JSON, default=list)
    chosen_messages: Mapped[list] = mapped_column(JSON, default=list)
    rejected_messages: Mapped[list] = mapped_column(JSON, default=list)
    label_or_target: Mapped[Any] = mapped_column(JSON, nullable=True)
    source_span_ids: Mapped[list] = mapped_column(JSON, default=list)
    source_document_ids: Mapped[list] = mapped_column(JSON, default=list)
    generation_candidate_ids: Mapped[list] = mapped_column(JSON, default=list)
    quality_status: Mapped[str] = mapped_column(String(32), default="review")
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    quality_dimensions: Mapped[dict] = mapped_column(JSON, default=dict)
    defect_taxonomy: Mapped[list] = mapped_column(JSON, default=list)
    trainer_visible_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    private_audit_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    split: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    version_id: Mapped[str | None] = mapped_column(
        ForeignKey("dataset_versions.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class QualityAssessmentDB(Base):
    __tablename__ = "quality_assessments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    example_id: Mapped[str] = mapped_column(ForeignKey("training_examples.id"), index=True)
    validator_name: Mapped[str] = mapped_column(String(128))
    validator_version: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(32), default="accepted")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list)
    concise_rationale: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GenerationCandidateDB(Base):
    __tablename__ = "generation_candidates"
    __table_args__ = (Index("ix_cand_fingerprint", "call_fingerprint"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    chunk_id: Mapped[str] = mapped_column(ForeignKey("chunks.id"), index=True)
    source_document_id: Mapped[str] = mapped_column(String(64), index=True)
    source_group_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    split: Mapped[str] = mapped_column(String(32))
    source_span_ids: Mapped[list] = mapped_column(JSON, default=list)
    topology: Mapped[str] = mapped_column(String(32))
    task_family: Mapped[str] = mapped_column(String(64))
    prompt_template_name: Mapped[str] = mapped_column(String(128), default="")
    prompt_template_version: Mapped[str] = mapped_column(String(64), default="")
    prompt_template_hash: Mapped[str] = mapped_column(String(64), default="")
    schema_hash: Mapped[str] = mapped_column(String(64), default="")
    provider: Mapped[str] = mapped_column(String(128), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    profile: Mapped[str] = mapped_column(String(64), default="")
    call_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    raw_output_artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    candidate_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="accepted")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class ModelCallDB(Base):
    __tablename__ = "model_calls"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    stage: Mapped[str] = mapped_column(String(64), default="")
    provider: Mapped[str] = mapped_column(String(128), default="")
    requested_model: Mapped[str] = mapped_column(String(128), default="")
    resolved_model: Mapped[str] = mapped_column(String(128), default="")
    profile: Mapped[str] = mapped_column(String(64), default="")
    prompt_template_hash: Mapped[str] = mapped_column(String(64), default="")
    request_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    schema_hash: Mapped[str] = mapped_column(String(64), default="")
    sampling_params: Mapped[dict] = mapped_column(JSON, default=dict)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    result_artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DatasetVersionDB(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (Index("ix_version_project", "project_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    semantic_version: Mapped[str] = mapped_column(String(32))
    parent_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manifest_artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quality_report_artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dataset_card_artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_manifest_artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    license_report_artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    privacy_report_artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    train_count: Mapped[int] = mapped_column(Integer, default=0)
    validation_count: Mapped[int] = mapped_column(Integer, default=0)
    test_count: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    release_status: Mapped[str] = mapped_column(String(32), default="draft")


class JobDB(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_job_project", "project_id"),
        Index("ix_job_state", "state"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    owner_principal: Mapped[str] = mapped_column(String(255))
    job_type: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32), default="queued")
    current_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    input_config_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    actual_cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    input: Mapped[dict] = mapped_column(JSON, default=dict)


class JobEventDB(Base):
    __tablename__ = "job_events"
    __table_args__ = (Index("ix_event_job_seq", "job_id", "sequence"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    level: Mapped[str] = mapped_column(String(16), default="info")
    event_type: Mapped[str] = mapped_column(String(64), default="log")
    stage: Mapped[str] = mapped_column(String(64), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    structured_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditEventDB(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    principal: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class CostLedgerDB(Base):
    __tablename__ = "cost_ledger"
    __table_args__ = (Index("ix_cost_job", "job_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage: Mapped[str] = mapped_column(String(64), default="")
    provider: Mapped[str] = mapped_column(String(128), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    price_snapshot_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    price_input_per_m: Mapped[float] = mapped_column(Float, default=0.0)
    price_output_per_m: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
