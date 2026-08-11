"""Canonical data schemas (spec §6, §12).

Pydantic models for the canonical internal data model and generation
candidates. Domain layer imports only Pydantic — never framework clients.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SourceKind(StrEnum):
    upload = "upload"
    local_path = "local_path"
    url = "url"
    repository = "repository"
    dataset = "dataset"


class LicenseStatus(StrEnum):
    allowed = "allowed"
    review = "review"
    blocked = "blocked"
    unknown = "unknown"


class IntakeStatus(StrEnum):
    pending = "pending"
    preflight_ok = "preflight_ok"
    preflight_failed = "preflight_failed"
    quarantine = "quarantine"
    completed = "completed"


class ExtractionStatus(StrEnum):
    pending = "pending"
    parsing = "parsing"
    parsed = "parsed"
    failed = "failed"
    partial = "partial"


class Topology(StrEnum):
    sft = "sft"
    preference = "preference"
    kto = "kto"
    evaluation = "evaluation"


class QualityStatus(StrEnum):
    accepted = "accepted"
    review = "review"
    rejected = "rejected"
    blocked = "blocked"


class JobState(StrEnum):
    queued = "queued"
    leased = "leased"
    running = "running"
    pausing = "pausing"
    paused = "paused"
    retry_wait = "retry_wait"
    succeeded = "succeeded"
    failed = "failed"
    cancelling = "cancelling"
    cancelled = "cancelled"


class ReleaseStatus(StrEnum):
    draft = "draft"
    reviewed = "reviewed"
    approved = "approved"
    published = "published"
    withdrawn = "withdrawn"


class SupportType(StrEnum):
    direct = "direct"
    derived = "derived"
    context = "context"


class TaskFamily(StrEnum):
    factual_explanation = "factual_explanation"
    procedure = "procedure"
    troubleshooting = "troubleshooting"
    comparison = "comparison"
    summarization = "summarization"
    extraction = "extraction"
    classification = "classification"
    refusal = "refusal"
    tool_use = "tool_use"


class None_:
    pass


# ---------------------------------------------------------------------------
# Canonical message / evidence / candidate schemas (§12.5/12.6)
# ---------------------------------------------------------------------------


class EvidenceRef(BaseModel):
    span_id: str
    support_type: SupportType = SupportType.direct


class CanonicalMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None
    tool_call_id: str | None = None


class GeneratedSFTCandidate(BaseModel):
    task_family: str
    difficulty: Literal["basic", "intermediate", "advanced"]
    messages: list[CanonicalMessage]
    evidence: list[EvidenceRef]
    answerability: Literal["answerable", "unanswerable"]
    concise_generation_note: str = ""
    chunk_id: str = ""
    source_document_id: str = ""
    source_group_id: str | None = None
    split: str = ""
    topology: str = "sft"

    @field_validator("messages")
    @classmethod
    def _validate_roles(cls, v: list[CanonicalMessage]) -> list[CanonicalMessage]:
        if not v:
            raise ValueError("at least one message required")
        first = v[0].role
        if first not in ("system", "user"):
            raise ValueError("conversation must start with system or user")
        # must contain an assistant turn
        if not any(m.role == "assistant" for m in v):
            raise ValueError("SFT candidate must contain an assistant turn")
        return v


class GeneratedPreferenceCandidate(BaseModel):
    task_family: str
    prompt_messages: list[CanonicalMessage]
    chosen_messages: list[CanonicalMessage]
    rejected_messages: list[CanonicalMessage]
    evidence: list[EvidenceRef]
    rejected_defect: Literal[
        "subtle_factual_error",
        "unsupported_inference",
        "instruction_omission",
        "reasoning_error",
        "citation_mismatch",
        "format_violation",
        "unhelpful_refusal",
        "unsafe_compliance",
        "irrelevant_detail",
    ]
    expected_preference_margin: Literal["small", "medium", "large"]
    concise_generation_note: str = ""
    chunk_id: str = ""
    source_document_id: str = ""
    source_group_id: str | None = None
    split: str = ""
    topology: str = "preference"

    @field_validator("chosen_messages", "rejected_messages")
    @classmethod
    def _has_assistant(cls, v: list[CanonicalMessage]) -> list[CanonicalMessage]:
        if not any(m.role == "assistant" for m in v):
            raise ValueError("must contain an assistant turn")
        return v


class GeneratedKTOCandidate(BaseModel):
    task_family: str
    messages: list[CanonicalMessage]
    desirability: Literal["good", "bad"]
    evidence: list[EvidenceRef]
    concise_generation_note: str = ""
    chunk_id: str = ""
    source_document_id: str = ""
    source_group_id: str | None = None
    split: str = ""
    topology: str = "kto"


class GeneratedEvaluationCandidate(BaseModel):
    task_family: str
    question: str
    reference_answer: str | None = None
    evidence: list[EvidenceRef]
    concise_generation_note: str = ""
    chunk_id: str = ""
    source_document_id: str = ""
    source_group_id: str | None = None
    split: str = ""
    topology: str = "evaluation"


class GeneratedBatch(BaseModel):
    candidates: list[Any] = Field(default_factory=list)
    generation_note: str = ""


# ---------------------------------------------------------------------------
# Dataset plan (§12.3)
# ---------------------------------------------------------------------------


class DatasetPlan(BaseModel):
    target_audience: str = "domain practitioners"
    languages: list[str] = ["en"]
    task_family_proportions: dict[str, float] = Field(default_factory=dict)
    difficulty_distribution: dict[str, float] = Field(default_factory=dict)
    answer_length_distribution: dict[str, int] = Field(default_factory=dict)
    question_form_diversity: int = 3
    examples_per_chunk: int = 1
    cross_document_allowance: float = 0.0
    refusal_proportion: float = 0.05
    preference_defect_distribution: dict[str, float] = Field(default_factory=dict)
    maximum_dataset_size: int = 10000
    quality_thresholds: dict[str, float] = Field(default_factory=dict)
    split_policy: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    concise_audit_note: str = ""

    def effective_proportions(self) -> dict[str, float]:
        return self.task_family_proportions or {"factual_explanation": 1.0}


# ---------------------------------------------------------------------------
# Entities (spec §6.2) — minimal canonical forms used across layers
# ---------------------------------------------------------------------------


class Project(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    slug: str
    display_name: str
    description: str = ""
    owner_principal: str
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    default_profile: str = "balanced"
    status: str = "active"
    tags: list[str] = Field(default_factory=list)


class SourceDocument(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    project_id: str
    original_name: str
    media_type: str
    byte_size: int
    sha256: str
    source_kind: SourceKind = SourceKind.upload
    source_locator_redacted: str = ""
    acquisition_time: datetime = Field(default_factory=utcnow)
    declared_license: str | None = None
    detected_license: str | None = None
    license_status: LicenseStatus = LicenseStatus.unknown
    privacy_classification: str = "unknown"
    language_candidates: list[str] = Field(default_factory=list)
    page_or_sheet_count: int | None = None
    intake_status: IntakeStatus = IntakeStatus.pending
    artifact_id_original: str | None = None
    group_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParsedDocument(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    source_document_id: str
    parser_name: str
    parser_version: str
    parser_config_hash: str
    canonical_docling_json_artifact_id: str | None = None
    markdown_artifact_id: str | None = None
    text_artifact_id: str | None = None
    diagnostics_artifact_id: str | None = None
    extraction_status: ExtractionStatus = ExtractionStatus.pending
    extraction_quality_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class SourceSpan(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    parsed_document_id: str
    page_number: int | None = None
    section_path: str = ""
    element_reference: str = ""
    character_start: int | None = None
    character_end: int | None = None
    bounding_boxes: list[Any] = Field(default_factory=list)
    quoted_text: str = ""
    sha256: str = ""


class Chunk(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    parsed_document_id: str
    source_document_id: str = ""
    source_group_id: str | None = None
    split_group_id: str | None = None
    ordinal: int = 0
    heading_path: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    structural_type: str = "text"
    main_text: str = ""
    rendered_context: str = ""
    token_count: int = 0
    source_span_ids: list[str] = Field(default_factory=list)
    chunker_name: str
    chunker_version: str
    chunker_config_hash: str
    sha256: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class GenerationCandidate(BaseModel):
    """A raw, persisted generation candidate before it becomes an example.

    Carries explicit lineage fields (never derived from identifier strings) so
    provenance and split can be resolved as data (§4 P0-2, §5.3, §A4).
    """

    model_config = ConfigDict(extra="allow")
    id: str
    project_id: str
    chunk_id: str
    source_document_id: str
    source_group_id: str | None = None
    split: str
    source_span_ids: list[str] = Field(default_factory=list)
    topology: str
    task_family: str
    prompt_template_name: str = ""
    prompt_template_version: str = ""
    prompt_template_hash: str = ""
    schema_hash: str = ""
    provider: str = ""
    model: str = ""
    profile: str = ""
    call_fingerprint: str = ""
    raw_output_artifact_id: str | None = None
    candidate_hash: str
    status: str = "accepted"
    created_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TrainingExample(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    project_id: str
    topology: Topology = Topology.sft
    system_messages: list[str] = Field(default_factory=list)
    prompt_messages: list[CanonicalMessage] = Field(default_factory=list)
    chosen_messages: list[CanonicalMessage] = Field(default_factory=list)
    rejected_messages: list[CanonicalMessage] = Field(default_factory=list)
    label_or_target: Any = None
    source_span_ids: list[str] = Field(default_factory=list)
    source_document_ids: list[str] = Field(default_factory=list)
    generation_candidate_ids: list[str] = Field(default_factory=list)
    quality_status: QualityStatus = QualityStatus.review
    quality_score: float = 0.0
    quality_dimensions: dict[str, float] = Field(default_factory=dict)
    defect_taxonomy: list[str] = Field(default_factory=list)
    trainer_visible_metadata: dict[str, Any] = Field(default_factory=dict)
    private_audit_metadata: dict[str, Any] = Field(default_factory=dict)
    content_hash: str = ""
    split: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class QualityAssessment(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    example_id: str
    validator_name: str
    validator_version: str
    policy_version: str = ""
    status: QualityStatus = QualityStatus.accepted
    score: float = 0.0
    reason_codes: list[str] = Field(default_factory=list)
    concise_rationale: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class DatasetVersion(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    project_id: str
    semantic_version: str
    parent_version_id: str | None = None
    manifest_artifact_id: str | None = None
    quality_report_artifact_id: str | None = None
    dataset_card_artifact_id: str | None = None
    source_manifest_artifact_id: str | None = None
    license_report_artifact_id: str | None = None
    privacy_report_artifact_id: str | None = None
    train_count: int = 0
    validation_count: int = 0
    test_count: int = 0
    content_hash: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    release_status: ReleaseStatus = ReleaseStatus.draft


class Job(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    project_id: str
    owner_principal: str
    job_type: str
    state: JobState = JobState.queued
    current_stage: str | None = None
    progress_current: int = 0
    progress_total: int = 0
    idempotency_key: str | None = None
    input_config_hash: str | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    attempt_count: int = 0
    max_attempts: int = 3
    cancellation_requested_at: datetime | None = None
    estimated_cost: float = 0.0
    actual_cost: float = 0.0
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error_summary: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)


class JobEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    job_id: str
    sequence: int = 0
    timestamp: datetime = Field(default_factory=utcnow)
    level: str = "info"
    event_type: str = "log"
    stage: str = ""
    message: str = ""
    structured_payload: dict[str, Any] = Field(default_factory=dict)
