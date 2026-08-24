"""Defect 3.7 (v0.2.1) — provenance location precision, end to end.

Precision must be DERIVED from what the parser actually recorded and must
survive persistence. These tests pin:

1. ``SourceSpan.with_derived_precision`` rule order (the single authority);
2. chunker location extraction from Docling ``prov`` (page + bbox) and honest
   degradation to section/chunk for markdown/text without location evidence;
3. service-level span construction from docling-shaped canonical input;
4. export-gate agreement with the domain derivation.
"""

from __future__ import annotations

import pytest

from knovaryn.domain.schemas import SourceSpan, SpanPrecision
from knovaryn.infrastructure.chunking.structure_aware import (
    ChunkCfg,
    _block_location,
    _merge_locations,
    chunk_document,
)
from knovaryn.pipeline.export.gate import LocationPrecision

# ---------------------------------------------------------------------------
# 1. derivation rules (with_derived_precision)
# ---------------------------------------------------------------------------


def _span(**kw) -> SourceSpan:
    defaults: dict = {"id": "s1", "parsed_document_id": "p1"}
    return SourceSpan(**{**defaults, **kw})


class TestDerivedPrecision:
    def test_bbox_plus_page_is_exact_bbox(self):
        s = _span(page_number=3, bounding_boxes=[{"page": 3}]).with_derived_precision()
        assert s.precision is SpanPrecision.exact_bbox

    def test_page_only_is_exact_page(self):
        s = _span(page_number=3).with_derived_precision()
        assert s.precision is SpanPrecision.exact_page

    def test_page_interval_is_page_range(self):
        s = _span(page_start=2, page_end=5).with_derived_precision()
        assert s.precision is SpanPrecision.page_range

    def test_section_path_is_section(self):
        s = _span(section_path="Assembly").with_derived_precision()
        assert s.precision is SpanPrecision.section

    def test_quoted_text_only_is_chunk(self):
        s = _span(quoted_text="torqued to 5 N·m").with_derived_precision()
        assert s.precision is SpanPrecision.chunk

    def test_nothing_is_unknown_never_fabricated(self):
        s = _span().with_derived_precision()
        assert s.precision is SpanPrecision.unknown

    def test_rule_order_bbox_beats_page(self):
        # exact_bbox outranks exact_page when both apply
        s = _span(page_number=1, bounding_boxes=[{"page": 1}], section_path="X")
        assert s.with_derived_precision().precision is SpanPrecision.exact_bbox

    def test_caller_asserted_precision_is_overwritten(self):
        # precision can never be hand-claimed higher than the data supports
        s = _span(quoted_text="x")
        s.precision = SpanPrecision.exact_bbox  # a lying caller...
        assert s.with_derived_precision().precision is SpanPrecision.chunk  # ...is corrected


# ---------------------------------------------------------------------------
# 2. chunker location extraction
# ---------------------------------------------------------------------------


class TestBlockLocation:
    def test_docling_prov_shape_becomes_canonical_location(self):
        block = {
            "type": "paragraph",
            "text": "The lid must be torqued.",
            "prov": [
                {
                    "page_no": 3,
                    "bbox": {
                        "l": 10.0,
                        "t": 20.0,
                        "r": 110.0,
                        "b": 40.0,
                        "coord_origin": "TOPLEFT",
                    },
                }
            ],
        }
        loc = _block_location(block)
        assert loc["pages"] == [3]
        assert len(loc["bboxes"]) == 1
        bb = loc["bboxes"][0]
        assert bb["page"] == 3
        assert bb["left"] == 10.0 and bb["right"] == 110.0
        assert bb["coord_origin"] == "TOPLEFT"
        assert bb["coord_system"] == "page"

    def test_parser_without_location_data_yields_empty(self):
        assert _block_location({"type": "paragraph", "text": "hi"}) == {
            "pages": [],
            "bboxes": [],
            "element_refs": [],
        }

    def test_merge_unions_pages_and_dedups_refs(self):
        units = [
            type(
                "U",
                (),
                {
                    "location": {
                        "pages": [1, 2],
                        "bboxes": [{"a": 1}],
                        "element_refs": ["docling#/main_text/0"],
                    }
                },
            )(),
            type(
                "U",
                (),
                {
                    "location": {
                        "pages": [2, 3],
                        "bboxes": [],
                        "element_refs": ["docling#/main_text/0", "docling#/main_text/1"],
                    }
                },
            )(),
        ]
        merged = _merge_locations(units)  # type: ignore[arg-type]
        assert merged["pages"] == [1, 2, 3]
        assert merged["element_refs"] == ["docling#/main_text/0", "docling#/main_text/1"]
        assert merged["bboxes"] == [{"a": 1}]


class TestChunkerCarriesLocation:
    def test_docling_blocks_produce_located_chunks(self):
        docling = {
            "main_text": [
                {
                    "text": "Widgets",
                    "label": "title",
                    "prov": [
                        {
                            "page_no": 1,
                            "bbox": {"l": 0, "t": 0, "r": 200, "b": 20, "coord_origin": "TOPLEFT"},
                        }
                    ],
                },
                {
                    "text": "A widget is a base plate plus a lid.",
                    "label": "text",
                    "prov": [
                        {
                            "page_no": 1,
                            "bbox": {"l": 0, "t": 30, "r": 200, "b": 60, "coord_origin": "TOPLEFT"},
                        }
                    ],
                },
                {
                    "text": "Torque the lid to 5 N·m.",
                    "label": "text",
                    "prov": [
                        {
                            "page_no": 2,
                            "bbox": {
                                "l": 0,
                                "t": 70,
                                "r": 200,
                                "b": 100,
                                "coord_origin": "TOPLEFT",
                            },
                        }
                    ],
                },
            ]
        }
        chunks = chunk_document(docling, ChunkCfg(target_tokens=50, min_tokens=5, max_tokens=300))
        assert chunks
        all_pages: set[int] = set()
        for c in chunks:
            all_pages.update(c.location.get("pages", []))
        assert all_pages == {1, 2}

    def test_markdown_fallback_has_empty_location_not_fake_pages(self):
        canonical = {
            "schema": "knovaryn-canonical/1.0",
            "blocks": [
                {"type": "heading", "text": "Assembly", "heading_path": ["Assembly"]},
                {
                    "type": "paragraph",
                    "text": "A widget is a base plate plus a lid.",
                    "heading_path": ["Assembly"],
                },
            ],
        }
        chunks = chunk_document(canonical, ChunkCfg(target_tokens=50, min_tokens=5, max_tokens=300))
        assert chunks
        assert all(c.location.get("pages") == [] for c in chunks)


# ---------------------------------------------------------------------------
# 3. service-level span construction
# ---------------------------------------------------------------------------


class TestServiceSpans:
    def _service(self):
        from knovaryn.application.service import ProjectService

        svc = ProjectService.__new__(ProjectService)  # only chunk_document under test
        # chunk_document reads the constructor-provided chunker config; supply
        # the default (empty) mapping the real __init__ would set.
        svc._chunk_config = {}
        return svc

    def test_spans_from_docling_input_carry_derived_precision(self):
        svc = self._service()
        parsed = type("P", (), {"id": "pd1", "source_document_id": "sd1"})()
        docling = {
            "main_text": [
                {
                    "text": "Report",
                    "label": "title",
                    "prov": [
                        {
                            "page_no": 1,
                            "bbox": {"l": 0, "t": 0, "r": 100, "b": 10, "coord_origin": "TOPLEFT"},
                        }
                    ],
                },
                {
                    "text": "Findings are material.",
                    "label": "text",
                    "prov": [
                        {
                            "page_no": 1,
                            "bbox": {"l": 0, "t": 20, "r": 100, "b": 50, "coord_origin": "TOPLEFT"},
                        }
                    ],
                },
            ]
        }
        chunks, spans = svc.chunk_document(parsed=parsed, canonical=docling)
        assert spans and len(spans) == len(chunks)
        for sp in spans:
            assert sp.precision in (SpanPrecision.exact_bbox, SpanPrecision.exact_page)
            assert sp.bounding_boxes, "docling-backed spans must carry bboxes"
        assert any(sp.precision is SpanPrecision.exact_bbox for sp in spans)

    def test_spans_from_markdown_are_honest_about_precision(self):
        svc = self._service()
        parsed = type("P", (), {"id": "pd2", "source_document_id": "sd2"})()
        canonical = {
            "schema": "knovaryn-canonical/1.0",
            "blocks": [
                {"type": "heading", "text": "Inspection", "heading_path": ["Inspection"]},
                {
                    "type": "paragraph",
                    "text": "Each unit is inspected for cracks.",
                    "heading_path": ["Inspection"],
                },
            ],
        }
        _, spans = svc.chunk_document(parsed=parsed, canonical=canonical)
        assert spans
        for sp in spans:
            assert sp.page_number is None
            assert sp.precision in (SpanPrecision.section, SpanPrecision.chunk)

    def test_multipage_span_reports_range_not_single_page(self):
        svc = self._service()
        parsed = type("P", (), {"id": "pd3", "source_document_id": "sd3"})()
        docling = {
            "main_text": [
                {
                    "text": "Part one.",
                    "label": "text",
                    "prov": [
                        {
                            "page_no": 1,
                            "bbox": {"l": 0, "t": 0, "r": 10, "b": 10, "coord_origin": "TOPLEFT"},
                        }
                    ],
                },
                {
                    "text": "Part two continues here.",
                    "label": "text",
                    "prov": [
                        {
                            "page_no": 2,
                            "bbox": {"l": 0, "t": 0, "r": 10, "b": 10, "coord_origin": "TOPLEFT"},
                        }
                    ],
                },
            ]
        }
        chunks, spans = svc.chunk_document(
            parsed=parsed,
            canonical=docling,
        )
        if len(chunks) == 1:
            sp = spans[0]
            assert sp.page_number is None
            assert (sp.page_start, sp.page_end) == (1, 2)
            assert sp.precision is SpanPrecision.page_range
        else:
            assert all(
                sp.precision in (SpanPrecision.exact_bbox, SpanPrecision.exact_page) for sp in spans
            )


# ---------------------------------------------------------------------------
# 4. export gate agrees with the domain derivation
# ---------------------------------------------------------------------------


class TestGateAgreement:
    def test_gate_uses_persisted_precision_field(self):
        s = _span(page_start=2, page_end=3).with_derived_precision()
        assert LocationPrecision.of_span(s) == LocationPrecision.PAGE_RANGE

    @pytest.mark.parametrize(
        "kwargs,expected",
        [
            ({"bounding_boxes": [{"page": 1}], "page_number": 1}, "exact_bbox"),
            ({"page_number": 4}, "exact_page"),
            ({"character_start": 9}, "chunk"),
            ({}, "unknown"),
        ],
    )
    def test_gate_legacy_duck_typed_spans_still_classify(self, kwargs, expected):
        class LegacySpan:
            pass

        ls = LegacySpan()
        for k, v in kwargs.items():
            setattr(ls, k, v)
        assert LocationPrecision.of_span(ls) == expected

    def test_gate_does_not_upgrade_chunk_to_exact_page(self):
        ls = type("L", (), {"character_start": 5, "quoted_text": "text"})()
        assert not LocationPrecision.at_least(
            LocationPrecision.of_span(ls), LocationPrecision.EXACT_PAGE
        )
