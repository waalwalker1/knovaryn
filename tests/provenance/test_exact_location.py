"""Regression tests: exact location/precision provenance (defect 4.6).

Location precision must be truthful — a span's precision is derived from what
is actually recorded, never claimed higher than the data supports.
"""

from knovaryn.pipeline.export.gate import LocationPrecision


class _Span:
    def __init__(self, *, bounding_boxes=None, page_number=None, character_start=None):
        self.bounding_boxes = bounding_boxes
        self.page_number = page_number
        self.character_start = character_start


class TestExactLocation:
    """Location precision must be truthful."""

    def test_chunk_precision_not_exact_page(self):
        """Span with chunk precision must not claim exact page traceability."""
        span = _Span(character_start=100)  # only chunk-level info
        precision = LocationPrecision.of_span(span)
        assert precision == LocationPrecision.CHUNK, precision
        # Chunk precision is NOT at least exact-page.
        assert not LocationPrecision.at_least(precision, LocationPrecision.EXACT_PAGE), (
            "chunk-level span must not claim exact-page traceability"
        )

    def test_bbox_preserved_where_available(self):
        """A span with bounding boxes reports exact_bbox precision."""
        span = _Span(
            bounding_boxes=[{"page": 1, "x0": 10, "y0": 20, "x1": 100, "y1": 40}],
            page_number=1,
        )
        precision = LocationPrecision.of_span(span)
        assert precision == LocationPrecision.EXACT_BBOX, precision
        assert LocationPrecision.at_least(precision, LocationPrecision.EXACT_PAGE), (
            "bbox precision subsumes exact page"
        )

    def test_exact_page(self):
        """A span with only a page number reports exact_page."""
        span = _Span(page_number=3)
        assert LocationPrecision.of_span(span) == LocationPrecision.EXACT_PAGE

    def test_unknown_precision(self):
        """A span with no location data is unknown — never fabricated."""
        span = _Span()
        assert LocationPrecision.of_span(span) == LocationPrecision.UNKNOWN

    def test_precision_ordering(self):
        """Precision levels order strictly by specificity."""
        assert LocationPrecision.at_least(LocationPrecision.EXACT_BBOX, LocationPrecision.CHUNK)
        assert LocationPrecision.at_least(LocationPrecision.EXACT_PAGE, LocationPrecision.CHUNK)
        assert not LocationPrecision.at_least(LocationPrecision.CHUNK, LocationPrecision.EXACT_PAGE)
        assert not LocationPrecision.at_least(LocationPrecision.UNKNOWN, LocationPrecision.CHUNK)
