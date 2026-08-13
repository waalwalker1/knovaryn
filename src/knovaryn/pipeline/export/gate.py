"""Export provenance gate (spec §15 / A6) — fail closed.

Before any accepted dataset is serialized, ``verify_provenance_before_export``
proves every example's lineage is real and resolvable — never parsed from a
display string:

* every ``source_document_id`` resolves to an existing ``SourceDocument`` in the
  SAME project;
* every ``source_span_id`` resolves to a ``SourceSpan`` whose owning
  ``ParsedDocument`` points back at one of the example's source documents;
* every ``generation_candidate_id`` resolves to an existing candidate in the
  same project;
* a recomputed ``content_hash`` matches the stored hash.

Any failure raises ``ExportError`` and the export is BLOCKED (fail closed) —
a successful export is never reported without a fully resolvable lineage
(contract rules 13/14).
"""

from __future__ import annotations

from typing import Any

from ...domain.errors import ExportError
from ...domain.hashing import ContentHasher
from ...domain.schemas import Topology, TrainingExample


def recompute_content_hash(ex: TrainingExample) -> str:
    """Canonical example hash, mirroring ``ProjectService._candidate_to_example``.

    Kept in one place so the gate verifies exactly what the pipeline produced.
    """
    if ex.topology == Topology.preference:
        return ContentHasher.cfg_hash(
            {
                "c": [m.content for m in ex.chosen_messages],
                "r": [m.content for m in ex.rejected_messages],
            }
        )
    if ex.topology == Topology.evaluation:
        question = ex.prompt_messages[0].content if ex.prompt_messages else ""
        reference = ex.chosen_messages[0].content if ex.chosen_messages else ""
        return ContentHasher.cfg_hash([question, reference])
    # sft and kto hash the ordered conversation content
    ordered = list(ex.system_messages)
    ordered += [m.content for m in ex.prompt_messages]
    ordered += [m.content for m in ex.chosen_messages]
    return ContentHasher.cfg_hash(ordered)


async def verify_provenance_before_export(examples: list[TrainingExample], resolver: Any) -> None:
    """Raise :class:`ExportError` on any unresolvable / cross-project lineage.

    ``resolver`` exposes async ``sources`` / ``spans`` / ``parsed`` /
    ``candidates`` repository accessors.
    """
    for ex in examples:
        if recompute_content_hash(ex) != ex.content_hash:
            raise ExportError(
                f"example {ex.id} content_hash mismatch: stored "
                f"{ex.content_hash[:16]}... does not match recomputed hash"
            )

        for sid in ex.source_document_ids:
            doc = await resolver.sources.get(sid)
            if doc is None:
                raise ExportError(
                    f"example {ex.id} references unresolvable source_document_id {sid}"
                )
            if doc.project_id != ex.project_id:
                raise ExportError(
                    f"example {ex.id} references source document {sid} from a "
                    "different project (cross-project lineage blocked)"
                )

        for span_id in ex.source_span_ids:
            span = await resolver.spans.get(span_id)
            if span is None:
                raise ExportError(
                    f"example {ex.id} references unresolvable source_span_id {span_id}"
                )
            parsed = await resolver.parsed.get(span.parsed_document_id)
            if parsed is None or parsed.source_document_id not in ex.source_document_ids:
                raise ExportError(
                    f"example {ex.id} span {span_id} does not resolve to a cited "
                    "source document (unresolvable span blocks export)"
                )

        for cid in ex.generation_candidate_ids:
            cand = await resolver.candidates.get(cid)
            if cand is None or cand.project_id != ex.project_id:
                raise ExportError(
                    f"example {ex.id} references unresolvable or cross-project "
                    f"generation_candidate_id {cid}"
                )
