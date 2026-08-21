"""Regression tests: lineage query completeness.

Lineage query must resolve example → document → artifact.
"""

import pytest

from knovaryn.pipeline.export.gate import verify_provenance_before_export


class _Store:
    def __init__(self, items=None):
        self._items = items or {}

    async def get(self, key):
        return self._items.get(key)


class _Resolver:
    def __init__(self, sources=None, spans=None, parsed=None, candidates=None):
        self.sources = _Store(sources)
        self.spans = _Store(spans)
        self.parsed = _Store(parsed)
        self.candidates = _Store(candidates)


class TestLineageQuery:
    """Lineage query must resolve example → document → artifact."""

    async def test_full_lineage_resolution(self):
        """Example → span → parsed document → source document all resolve."""
        from knovaryn.domain.schemas import (
            CanonicalMessage,
            Topology,
            TrainingExample,
        )
        from knovaryn.pipeline.export.gate import recompute_content_hash

        class _Doc:
            project_id = "p1"

        class _Span:
            parsed_document_id = "parsed1"
            page_number = 2

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

        resolver = _Resolver(
            sources={"doc1": _Doc()},
            spans={"span1": _Span()},
            parsed={"parsed1": _Parsed()},
            candidates={"cand1": _Cand()},
        )
        # Must not raise — full lineage resolves.
        await verify_provenance_before_export([ex], resolver)

    async def test_broken_span_link_blocked(self):
        """A span whose parsed doc doesn't point at a cited source is blocked."""
        from knovaryn.domain.errors import ExportError
        from knovaryn.domain.schemas import (
            CanonicalMessage,
            Topology,
            TrainingExample,
        )
        from knovaryn.pipeline.export.gate import recompute_content_hash

        class _Doc:
            project_id = "p1"

        class _Span:
            parsed_document_id = "parsedX"

        class _Parsed:
            source_document_id = "other-doc"

        class _Cand:
            project_id = "p1"

        ex = TrainingExample(
            id="ex2",
            project_id="p1",
            topology=Topology.sft,
            prompt_messages=[CanonicalMessage(role="user", content="Q?")],
            chosen_messages=[CanonicalMessage(role="assistant", content="A.")],
            source_document_ids=["doc1"],
            source_span_ids=["span1"],
            generation_candidate_ids=["cand1"],
        )
        ex.content_hash = recompute_content_hash(ex)

        resolver = _Resolver(
            sources={"doc1": _Doc()},
            spans={"span1": _Span()},
            parsed={"parsedX": _Parsed()},
            candidates={"cand1": _Cand()},
        )
        with pytest.raises(ExportError, match="span"):
            await verify_provenance_before_export([ex], resolver)
