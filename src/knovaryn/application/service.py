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
    GenerationCandidate,
    ParsedDocument,
    Project,
    QualityStatus,
    SourceDocument,
    SourceSpan,
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
    spans: list[SourceSpan] = field(default_factory=list)
    candidates: list[GenerationCandidate] = field(default_factory=list)
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
    def chunk_document(
        self, *, parsed: ParsedDocument, canonical: dict[str, Any]
    ) -> tuple[list[Chunk], list[SourceSpan]]:
        cfg = ChunkCfg.from_dict(self._chunk_config)
        results = chunk_document(canonical, cfg)
        chunks: list[Chunk] = []
        spans: list[SourceSpan] = []
        for i, res in enumerate(results):
            span_ids: list[str] = []
            # one real, persisted span per chunk (character-located, quoted text)
            span = SourceSpan(
                id=self._ids.new_handle("sp"),
                parsed_document_id=parsed.id,
                page_number=None,
                section_path="/".join(res.heading_path),
                element_reference=f"chunk:{i}",
                character_start=0,
                character_end=len(res.main_text),
                quoted_text=res.main_text,
                sha256=normalize_hash(res.main_text),
            )
            spans.append(span)
            span_ids.append(span.id)
            chunks.append(
                Chunk(
                    id=self._ids.new_handle("ck"),
                    parsed_document_id=parsed.id,
                    source_document_id=parsed.source_document_id,
                    source_group_id=None,
                    ordinal=i,
                    heading_path=res.heading_path,
                    structural_type="text",
                    main_text=res.main_text,
                    rendered_context=res.context_text,
                    token_count=len(res.main_text.split()),
                    source_span_ids=span_ids,
                    chunker_name="structure_aware",
                    chunker_version="1",
                    chunker_config_hash=cfg.config_hash(),
                    sha256=normalize_hash(res.main_text),
                    metadata={"source_id": parsed.source_document_id},
                )
            )
        return chunks, spans

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
            chunks, spans = self.chunk_document(parsed=parsed, canonical=canonical)
            for c in chunks:
                c.source_group_id = source.group_key or source.id
                c.split = None  # set after split assignment below
            result.chunks.extend(chunks)
            result.spans.extend(spans)

        if not result.chunks:
            result.notes.append("no chunks produced; nothing to generate")
            return result

        # source-group split at SOURCE level before generation (P0-2/B1)
        split = assign_splits(sources, strategy="grouped_random", seed=42)
        # propagate split to each chunk as DATA (explicit field), not parsed from ids
        for source in sources:
            s = split.split_of(source.id) or ""
            for c in result.chunks:
                if c.source_document_id == source.id:
                    c.split = s
        effective = {c.id: c.split for c in result.chunks if c.split}
        result.notes.append(
            f"split: {split.strategy} (assigned {len(effective)}/{len(result.chunks)} chunks)"
        )

        # build span_texts from REAL persisted spans (cited-only evidence, C2)
        span_texts: dict[str, str] = {sp.id: sp.quoted_text for sp in result.spans}

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

        # build persisted candidates + training examples from candidates; validate
        gen_candidates, generated_of = _build_candidates(
            ids=self._ids, project=project, gen_outcome=gen_outcome
        )
        result.candidates = gen_candidates

        examples: list[TrainingExample] = []
        assessments: list[Any] = []
        topology_of: dict[str, str] = {}
        for cand in gen_candidates:
            topo = cand.topology
            split_v = cand.split
            source_document_id = cand.source_document_id
            pid = cand.id
            ex = _candidate_to_example(
                ex_id=self._ids.new_handle("ex"),
                project_id=project.id,
                topo=topo,
                cand=generated_of[pid],
                source_span_ids=cand.source_span_ids,
                split=split_v,
            )
            # real provenance: explicit document + candidate references (P0-1)
            ex.source_document_ids = [source_document_id] if source_document_id else []
            ex.generation_candidate_ids = [pid]
            # validate against ONLY cited evidence
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


def _build_candidates(
    *, ids: IdGenerator, project: Project, gen_outcome: Any
) -> tuple[list[GenerationCandidate], dict[str, Any]]:
    """Persist each generated candidate carrying explicit lineage (P0-1).

    Returns ``(candidates, generated_of)`` where ``generated_of`` maps each
    persisted candidate id to its Generated* object (used to build examples).
    Provenance fields are explicit data, never parsed from identifier strings.
    """
    from ..domain.hashing import normalize_hash

    candidates: list[GenerationCandidate] = []
    generated_of: dict[str, Any] = {}
    for batch in gen_outcome.batches:
        for gen in batch.candidates:
            cand = GenerationCandidate(
                id=ids.new_handle("cand"),
                project_id=project.id,
                chunk_id=getattr(gen, "chunk_id", "") or "",
                source_document_id=getattr(gen, "source_document_id", "") or "",
                source_group_id=getattr(gen, "source_group_id", None),
                split=getattr(gen, "split", "") or "",
                source_span_ids=[e.span_id for e in getattr(gen, "evidence", []) if e.span_id],
                topology=getattr(gen, "topology", "sft") or "sft",
                task_family=getattr(gen, "task_family", "") or "",
                provider=getattr(gen, "provider", "") or "",
                model=getattr(gen, "model", "") or "",
                candidate_hash=normalize_hash(
                    getattr(gen, "concise_generation_note", "") or repr(gen)[:2000]
                ),
            )
            candidates.append(cand)
            generated_of[cand.id] = gen
    return candidates, generated_of


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
