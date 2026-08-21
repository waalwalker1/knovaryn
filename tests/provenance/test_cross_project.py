"""Regression tests: cross-project provenance rejection.

Cross-project lineage must be rejected — an example must never cite evidence
owned by a different project.
"""

import pytest

from knovaryn.domain.errors import ExportError
from knovaryn.pipeline.export.gate import recompute_content_hash, verify_provenance_before_export


class _Store:
    def __init__(self, items=None):
        self._items = items or {}

    async def get(self, key):
        return self._items.get(key)


class TestCrossProject:
    """Cross-project lineage must be rejected."""

    async def test_cross_project_source_rejected(self):
        """A source document owned by another project blocks export."""
        from knovaryn.domain.schemas import (
            CanonicalMessage,
            Topology,
            TrainingExample,
        )

        class _Doc:
            project_id = "p2"  # different project

        class _Span:
            parsed_document_id = "parsed1"

        class _Parsed:
            source_document_id = "doc1"

        class _Cand:
            project_id = "p1"

        ex = TrainingExample(
            id="ex1",
            project_id="p1",
            topology=Topology.sft,
            prompt_messages=[CanonicalMessage(role="user", content="Q?")],
            chosen_messages=[CanonicalMessage(role="assistant", content="A.")],
            source_document_ids=["doc1"],
            source_span_ids=["span1"],
            generation_candidate_ids=["cand1"],
        )
        ex.content_hash = recompute_content_hash(ex)

        resolver = type(
            "R",
            (),
            {
                "sources": _Store({"doc1": _Doc()}),
                "spans": _Store({"span1": _Span()}),
                "parsed": _Store({"parsed1": _Parsed()}),
                "candidates": _Store({"cand1": _Cand()}),
            },
        )()
        with pytest.raises(ExportError, match="different project"):
            await verify_provenance_before_export([ex], resolver)

    async def test_cross_project_candidate_rejected(self):
        """A generation candidate owned by another project blocks export."""
        from knovaryn.domain.schemas import (
            CanonicalMessage,
            Topology,
            TrainingExample,
        )

        class _Doc:
            project_id = "p1"

        class _Span:
            parsed_document_id = "parsed1"

        class _Parsed:
            source_document_id = "doc1"

        class _Cand:
            project_id = "p9"  # different project

        ex = TrainingExample(
            id="ex3",
            project_id="p1",
            topology=Topology.sft,
            prompt_messages=[CanonicalMessage(role="user", content="Q?")],
            chosen_messages=[CanonicalMessage(role="assistant", content="A.")],
            source_document_ids=["doc1"],
            source_span_ids=["span1"],
            generation_candidate_ids=["cand1"],
        )
        ex.content_hash = recompute_content_hash(ex)

        resolver = type(
            "R",
            (),
            {
                "sources": _Store({"doc1": _Doc()}),
                "spans": _Store({"span1": _Span()}),
                "parsed": _Store({"parsed1": _Parsed()}),
                "candidates": _Store({"cand1": _Cand()}),
            },
        )()
        with pytest.raises(ExportError, match="cross-project"):
            await verify_provenance_before_export([ex], resolver)
