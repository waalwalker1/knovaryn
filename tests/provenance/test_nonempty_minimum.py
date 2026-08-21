"""Regression tests: non-empty minimum provenance (defect 4.7).

Export must be blocked on empty provenance arrays — an example without full
lineage is untraceable and must never be released.
"""

import pytest

from knovaryn.domain.errors import ExportError
from knovaryn.domain.schemas import (
    CanonicalMessage,
    Topology,
    TrainingExample,
)
from knovaryn.pipeline.export.gate import recompute_content_hash, verify_provenance_before_export


def _example(**kw) -> TrainingExample:
    defaults = {
        "id": "ex1",
        "project_id": "p1",
        "topology": Topology.sft,
        "prompt_messages": [CanonicalMessage(role="user", content="What is X?")],
        "chosen_messages": [CanonicalMessage(role="assistant", content="X is Y.")],
        "source_document_ids": ["doc1"],
        "source_span_ids": ["span1"],
        "generation_candidate_ids": ["cand1"],
    }
    defaults.update(kw)
    ex = TrainingExample(**defaults)
    ex.content_hash = recompute_content_hash(ex)
    return ex


class _Resolver:
    """Minimal resolver with in-memory stores."""

    def __init__(self, sources=None, spans=None, parsed=None, candidates=None):
        class _Store:
            def __init__(self, items):
                self._items = items or {}

            async def get(self, key):
                return self._items.get(key)

        self.sources = _Store(sources or {})
        self.spans = _Store(spans or {})
        self.parsed = _Store(parsed or {})
        self.candidates = _Store(candidates or {})


class TestNonemptyMinimum:
    """Export must be blocked on empty provenance arrays."""

    async def test_empty_source_document_ids_blocked(self):
        ex = _example(source_document_ids=[])
        ex.content_hash = recompute_content_hash(ex)
        with pytest.raises(ExportError, match="empty source_document_ids"):
            await verify_provenance_before_export([ex], _Resolver())

    async def test_empty_source_span_ids_blocked(self):
        ex = _example(source_span_ids=[])
        ex.content_hash = recompute_content_hash(ex)
        with pytest.raises(ExportError, match="empty source_span_ids"):
            await verify_provenance_before_export([ex], _Resolver())

    async def test_empty_generation_candidate_ids_blocked(self):
        ex = _example(generation_candidate_ids=[])
        ex.content_hash = recompute_content_hash(ex)
        with pytest.raises(ExportError, match="empty generation_candidate_ids"):
            await verify_provenance_before_export([ex], _Resolver())

    async def test_full_provenance_resolves(self):
        """A fully-resolvable example passes the gate (control case)."""

        from knovaryn.domain.schemas import GenerationCandidate

        ex = _example()
        cand = GenerationCandidate(
            id="cand1",
            project_id="p1",
            chunk_id="ch1",
            source_document_id="doc1",
            split="train",
            topology="sft",
            task_family="factual_explanation",
            candidate_hash="abc",
        )
        resolver = _Resolver(candidates={"cand1": cand})

        # sources/spans/parsed stores are empty but example cites none beyond
        # the candidate — wait, it cites doc1/span1; provide them.
        class _Doc:
            project_id = "p1"

        class _Span:
            parsed_document_id = "parsed1"

        class _Parsed:
            source_document_id = "doc1"

        resolver.sources._items["doc1"] = _Doc()
        resolver.spans._items["span1"] = _Span()
        resolver.parsed._items["parsed1"] = _Parsed()
        await verify_provenance_before_export([ex], resolver)  # should not raise
