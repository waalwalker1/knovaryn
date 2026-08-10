"""Application services (spec §12, §17).

High-level, framework-free operations that CLI / MCP / REST wrap. The core
``run_pipeline`` executes the full offline flow — intake → parse → chunk →
split → plan → generate → validate → approve → version → export — using the
deterministic fake provider and local stores, so the product is fully
functional with no credentials. Model-driven generation is injected via the
gateway; a live gateway swaps in seamlessly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from ..domain.hashing import ContentHasher, normalize_hash
from ..domain.ids import IdGenerator
from ..domain.schemas import (
    Chunk,
    DatasetPlan,
    DatasetVersion,
    ExtractionStatus,
    ParsedDocument,
    Project,
    QualityStatus,
    SourceDocument,
    Topology,
    TrainingExample,
)
from ..infrastructure.chunking.structure_aware import ChunkCfg, chunk_document
from ..infrastructure.models.gateway import ModelGateway
from ..pipeline.export.exporters import export_jsonl
from ..pipeline.export.release import build_release_bundle
from ..pipeline.generate import Generator
from ..pipeline.planner import plan as plan_dataset
from ..pipeline.quality.artifact import diagnose_example
from ..pipeline.quality.reports import build_quality_report
from ..pipeline.quality.validators import (
    CompletenessValidator,
    FormatValidator,
    GroundingValidator,
    RefusalValidator,
    ValidatorContext,
    assemble_decision,
)
from ..pipeline.split import assign_splits


@dataclass
class PipelineResult:
    project: Project
    parsed: list[ParsedDocument] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    examples: list[TrainingExample] = field(default_factory=list)
    version: DatasetVersion | None = None
    quality: dict[str, Any] = field(default_factory=dict)
    release_bundle_bytes: bytes = b""
    release_sha256: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project.id,
            "parsed_count": len(self.parsed),
            "chunk_count": len(self.chunks),
            "example_count": len(self.examples),
            "accepted_count": sum(
                1 for e in self.examples if e.quality_status == QualityStatus.accepted
            ),
            "quality": self.quality,
            "release_sha256": self.release_sha256,
            "version": self.version.semantic_version if self.version else None,
            "notes": self.notes,
        }


class ProjectService:
    """Orchestrates the full pipeline for one project. Thread-safe per call."""

    def __init__(
        self,
        *,
        ids: IdGenerator | None = None,
        gateway: ModelGateway | None = None,
        workdir: str | None = None,
        chunk_config: dict[str, Any] | None = None,
    ) -> None:
        self._ids = ids or IdGenerator()
        self._workdir = workdir
        self._chunk_config = chunk_config or {}
        if gateway is not None:
            self._gateway = gateway
        else:
            self._gateway = ModelGateway(
                generator_model="fake", critic_model="fake", verifier_model="fake"
            )

    # -- intake + parse (text fallback, docling optional) --------------------
    async def ingest_and_parse(
        self, *, project: Project, source: SourceDocument, content: str
    ) -> tuple[ParsedDocument, dict[str, Any]]:
        from ..infrastructure.docling.adapter import DoclingAdapter

        raw = content.encode("utf-8")
        adapter = DoclingAdapter(ids=self._ids)
        outcome = await adapter.parse(source, raw, config={})
        parsed = ParsedDocument(
            id=self._ids.new_handle("par"),
            source_document_id=source.id,
            parser_name=outcome.parser_name,
            parser_version=outcome.parser_version,
            parser_config_hash="demo",
            canonical_docling_json_artifact_id=self._ids.new_handle("art"),
            markdown_artifact_id=self._ids.new_handle("art"),
            text_artifact_id=self._ids.new_handle("art"),
            extraction_status=ExtractionStatus.parsed,
            extraction_quality_summary=outcome.diagnostics,
        )
        return parsed, outcome.canonical_json

    # -- chunking ------------------------------------------------------------
    def chunk_document(self, *, parsed: ParsedDocument, canonical: dict[str, Any]) -> list[Chunk]:
        cfg = ChunkCfg.from_dict(self._chunk_config)
        results = chunk_document(canonical, cfg)
        chunks: list[Chunk] = []
        for i, res in enumerate(results):
            chunks.append(
                Chunk(
                    id=self._ids.new_handle("ck"),
                    parsed_document_id=parsed.id,
                    ordinal=i,
                    heading_path=res.heading_path,
                    structural_type="text",
                    main_text=res.main_text,
                    rendered_context=res.context_text,
                    token_count=len(res.main_text.split()),
                    source_span_ids=[f"span_{normalize_hash(res.main_text)[:8]}_{i}"],
                    chunker_name="structure_aware",
                    chunker_version="1",
                    chunker_config_hash=cfg.config_hash(),
                    sha256=normalize_hash(res.main_text),
                    metadata={"source_id": parsed.source_document_id},
                )
            )
        return chunks

    # -- full pipeline -------------------------------------------------------
    async def run_pipeline(
        self,
        *,
        project: Project,
        sources: list[SourceDocument],
        contents: list[str],
        plan: DatasetPlan | None = None,
    ) -> PipelineResult:
        plan = plan or DatasetPlan(
            task_family_proportions={
                "factual_explanation": 0.5,
                "procedure": 0.3,
                "comparison": 0.2,
            }
        )
        result = PipelineResult(project=project)

        # parse + chunk each source
        for source, content in zip(sources, contents, strict=True):
            parsed, canonical = await self.ingest_and_parse(
                project=project, source=source, content=content
            )
            result.parsed.append(parsed)
            result.chunks.extend(self.chunk_document(parsed=parsed, canonical=canonical))

        if not result.chunks:
            result.notes.append("no chunks produced; nothing to generate")
            return result

        # source-group split at SOURCE level before generation
        split = assign_splits(sources, strategy="grouped_random", seed=42)
        chunk_split = {
            c.id: split.split_of(_chunk_source(c, sources)) or "train" for c in result.chunks
        }
        result.notes.append(f"split: {split.strategy}")

        # plan + generate candidates
        plan_result = plan_dataset(plan, chunk_count=len(result.chunks))
        gen = Generator(gateway=self._gateway)
        gen_outcome = await gen.generate_for_plan(
            chunks=result.chunks,
            plan=plan_result,
            source_text_for=lambda c: getattr(c, "main_text", ""),
            span_ids_for=lambda c: getattr(c, "source_span_ids", []),
            seed_base=7,
        )
        result.notes.append(f"generated {gen_outcome.candidates_generated} candidates")

        # build training examples from candidates + validate
        examples: list[TrainingExample] = []
        assessments: list[Any] = []
        topology_of: dict[str, str] = {}
        span_texts: dict[str, str] = {}
        for chunk in result.chunks:
            for span_id in chunk.source_span_ids:
                span_texts[span_id] = chunk.main_text
            if not chunk.source_span_ids:
                span_texts[f"auto:{chunk.id}"] = chunk.main_text

        for batch in gen_outcome.batches:
            for cand in batch.candidates:
                topo = _topology_of_candidate(cand)
                ex = _candidate_to_example(
                    ex_id=self._ids.new_handle("ex"),
                    project_id=project.id,
                    topo=topo,
                    cand=cand,
                    source_span_ids=_candidate_span_ids(cand),
                    split=chunk_split.get(_candidate_chunk(cand), "train"),
                )
                # validate
                ctx = ValidatorContext(source_texts=span_texts, policy_version="1")
                sub = await self._validate(ex, ctx, is_preference=(topo == "preference"))
                assessments.append(sub)
                ex.quality_status = sub.status
                ex.quality_score = sub.score
                ex.quality_dimensions = _dims_from(sub)
                topology_of[ex.id] = topo
                if sub.status == QualityStatus.accepted:
                    examples.append(ex)

        result.examples = examples
        result.quality = build_quality_report(assessments, topologies=topology_of).to_dict()

        # version + export accepted examples
        if examples:
            version = DatasetVersion(
                id=self._ids.new_handle("ver"),
                project_id=project.id,
                semantic_version="0.1.0",
                train_count=sum(1 for e in examples if e.split == "train"),
                validation_count=sum(1 for e in examples if e.split == "validation"),
                test_count=sum(1 for e in examples if e.split == "test"),
                content_hash=ContentHasher.cfg_hash([e.content_hash for e in examples]),
            )
            result.version = version
            bundle = build_release_bundle(
                version=version.semantic_version,
                project_id=project.id,
                session_note="offline demo pipeline",
                split_files=_split_bytes(examples),
                dataset_card={"name": project.display_name, "language": ["en"]},
                quality_report=result.quality,
                license_summary={"status": "review", "count": 0},
                privacy_summary={"pii_findings": 0, "high_confidence": False},
                source_manifest={"sources": len(sources)},
                readme=_default_readme(project, examples),
            )
            result.release_bundle_bytes = bundle.to_zip()
            result.release_sha256 = bundle.sha256()
        return result

    async def _validate(
        self, ex: TrainingExample, ctx: ValidatorContext, *, is_preference: bool
    ) -> Any:
        grounding = await GroundingValidator().assess(ex, ctx)
        complete = await CompletenessValidator().assess(ex, ctx)
        fmt = await FormatValidator().assess(ex, ctx)
        refusal = await RefusalValidator().assess(ex, ctx)
        diag = diagnose_example(ex)
        artifact = _artifact_assessment(ex, diag)
        overall = assemble_decision(
            [grounding, complete, fmt, refusal, artifact],
            example_id=ex.id,
            is_preference=is_preference,
        )
        return overall


def _candidate_to_example(
    *, ex_id: str, project_id: str, topo: str, cand: Any, source_span_ids: list[str], split: str
) -> TrainingExample:
    from ..domain.schemas import CanonicalMessage

    if topo == "preference":
        return TrainingExample(
            id=ex_id,
            project_id=project_id,
            topology=Topology.preference,
            prompt_messages=[
                CanonicalMessage(
                    role="user",
                    content=(cand.prompt_messages[0].content if cand.prompt_messages else ""),
                )
            ],
            chosen_messages=cand.chosen_messages,
            rejected_messages=cand.rejected_messages,
            source_span_ids=source_span_ids,
            content_hash=ContentHasher.cfg_hash(
                {
                    "c": [m.content for m in cand.chosen_messages],
                    "r": [m.content for m in cand.rejected_messages],
                }
            ),
            split=split,
        )
    if topo == "kto":
        return TrainingExample(
            id=ex_id,
            project_id=project_id,
            topology=Topology.kto,
            prompt_messages=cand.messages[:-1] if len(cand.messages) > 1 else [],
            chosen_messages=[cand.messages[-1]] if cand.messages else [],
            label_or_target=cand.desirability,
            source_span_ids=source_span_ids,
            content_hash=ContentHasher.cfg_hash([m.content for m in cand.messages]),
            split=split,
        )
    if topo == "evaluation":
        return TrainingExample(
            id=ex_id,
            project_id=project_id,
            topology=Topology.evaluation,
            prompt_messages=[CanonicalMessage(role="user", content=cand.question)],
            chosen_messages=[
                CanonicalMessage(role="assistant", content=cand.reference_answer or "")
            ],
            source_span_ids=source_span_ids,
            content_hash=ContentHasher.cfg_hash([cand.question, cand.reference_answer or ""]),
            split=split,
        )
    # sft
    return TrainingExample(
        id=ex_id,
        project_id=project_id,
        topology=Topology.sft,
        system_messages=[m.content for m in cand.messages if m.role == "system"],
        prompt_messages=[m for m in cand.messages if m.role == "user"],
        chosen_messages=[m for m in cand.messages if m.role == "assistant"],
        source_span_ids=source_span_ids,
        content_hash=ContentHasher.cfg_hash([m.content for m in cand.messages]),
        split=split,
    )


def _topology_of_candidate(cand: Any) -> str:
    from ..domain.schemas import (
        GeneratedEvaluationCandidate,
        GeneratedKTOCandidate,
        GeneratedPreferenceCandidate,
    )

    if isinstance(cand, GeneratedPreferenceCandidate):
        return "preference"
    if isinstance(cand, GeneratedKTOCandidate):
        return "kto"
    if isinstance(cand, GeneratedEvaluationCandidate):
        return "evaluation"
    return "sft"


def _candidate_span_ids(cand: Any) -> list[str]:
    return [e.span_id for e in cand.evidence if e.span_id]


def _candidate_chunk(cand: Any) -> str:
    for e in cand.evidence:
        if e.span_id:
            return cast(str, e.span_id.split("_")[0])
    return ""


def _chunk_source(chunk: Chunk, sources: list[SourceDocument]) -> str:
    # In the demo, chunks are mapped by parsing the span/candidate id. We map
    # chunk -> its source via the parsed document order stored in metadata.
    return chunk.metadata.get("source_id") or (sources[0].id if sources else "")


def _dims_from(assessment: Any) -> dict[str, float]:
    ev = (
        assessment.evidence.get("per_validator", {})
        if isinstance(assessment.evidence, dict)
        else {}
    )
    return dict(ev) if isinstance(ev, dict) else {}


def _artifact_assessment(ex: TrainingExample, diag: Any) -> Any:
    from ..domain.schemas import QualityAssessment

    score = diag.artifact_resistance
    return QualityAssessment(
        id="",
        example_id=ex.id,
        validator_name="artifact_resistance",
        validator_version="1",
        policy_version="1",
        status=QualityStatus.accepted if score >= 0.75 else QualityStatus.review,
        score=score,
        reason_codes=diag.reasons,
        concise_rationale="artifact-resistance heuristic",
    )


def _split_bytes(examples: list[TrainingExample]) -> dict[str, bytes]:
    out: dict[str, Any] = {}
    for split in ("train", "validation", "test"):
        use = [e for e in examples if e.split == split]
        out[split] = export_jsonl(use, path="").bytes
    return dict(out)


def _default_readme(project: Project, examples: list[TrainingExample]) -> str:
    return (
        f"# {project.display_name}\n\n"
        f"Generated by Knovaryn. {len(examples)} accepted examples.\n"
        "For research/training purposes under the project's declared licence. "
        "Verify licensing and privacy before public release.\n"
    )
