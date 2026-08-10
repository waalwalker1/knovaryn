"""Docling adapter + fallback parser (spec §9, ADR 0003).

When the ``docling`` extra is installed, uses real Docling via
``DoclingResourceGuard`` and persists the DoclingDocument JSON as the canonical
artifact (Markdown/plain text are derivatives). When Docling is not installed,
degrades to a safe, structurally-faithful fallback parser so intake, chunking,
generation, and the offline demo still work. Never claims error-free extraction.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

from ...domain import schemas
from ...domain.errors import ConfigurationError
from ...domain.hashing import ContentHasher
from ...domain.ids import IdGenerator
from .guard import DoclingResourceGuard
from .ocr import OCRProfile, detect_available_ocr_engines

log = logging.getLogger("knovaryn.docling")


def docling_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("docling") is not None


@dataclass
class ParseOutcome:
    canonical_json: dict[str, Any]
    markdown: str
    plain_text: str
    diagnostics: dict[str, Any]
    parser_name: str
    parser_version: str
    pages: int
    used_docling: bool
    cleanup: str = ""


class DoclingAdapter:
    """Version-aware parser. Validates configured options at startup."""

    def __init__(
        self,
        *,
        ids: IdGenerator,
        ocr_profile: OCRProfile | None = None,
        recycle_documents: int = 25,
    ) -> None:
        self._ids = ids
        self.ocr = ocr_profile or OCRProfile()
        self.recycle_documents = recycle_documents
        self._parses_this_worker = 0
        self._validate_options()

    def _validate_options(self) -> None:
        if self.ocr.mode not in ("off", "auto", "on", "force_engine"):
            raise ConfigurationError(f"invalid ocr_mode: {self.ocr.mode!r}")

    async def parse(
        self, source: schemas.SourceDocument, raw: bytes, *, config: dict[str, Any]
    ) -> ParseOutcome:
        import importlib.util

        self._parses_this_worker += 1
        engine_engines = detect_available_ocr_engines()
        config_hash = ContentHasher.cfg_hash(config)

        if importlib.util.find_spec("docling") is not None:
            try:
                return await asyncio.to_thread(
                    self._parse_docling, source, raw, config, config_hash, engine_engines
                )
            except Exception as exc:  # noqa: BLE001 - fall back safely
                log.warning("docling parse failed (%s); falling back to safe parser", exc)
        # Safe fallback parser
        outcome = self._parse_fallback(source, raw, config_hash, engine_engines)
        return outcome

    # ---- real docling (opt-in) ----
    def _parse_docling(
        self,
        source: schemas.SourceDocument,
        raw: bytes,
        config: dict[str, Any],
        config_hash: str,
        engine_engines: list[str],
    ) -> ParseOutcome:
        from docling.document_converter import DocumentConverter

        converter_config: dict[str, Any] = {}
        converter = DocumentConverter(**converter_config)
        conv_result = converter.convert(self._bytes_to_path(source, raw))
        guard = DoclingResourceGuard(conv_result)

        # persist canonical docling JSON then release
        docling_json = conv_result.document.export_to_dict()

        markdown = ""
        try:
            markdown = conv_result.document.export_to_markdown()
        except Exception:  # noqa: BLE001
            markdown = ""
        plain = _strip_markdown(markdown)
        cleanup = guard.cleanup_path.name if guard.cleanup_path else ""
        pages = len(getattr(conv_result.document, "pages", []) or [])

        diagnostics = {
            "parser": "docling",
            "parser_version": getattr(conv_result.document, "format_version", "unknown"),
            "page_count": pages,
            "text_chars": len(plain),
            "ocr_engines": engine_engines,
        }
        return ParseOutcome(
            canonical_json=docling_json,
            markdown=markdown,
            plain_text=plain,
            diagnostics=diagnostics,
            parser_name="docling",
            parser_version=str(getattr(conv_result.document, "format_version", "unknown")),
            pages=pages,
            used_docling=True,
            cleanup=cleanup or "guard",
        )

    def _bytes_to_path(self, source: schemas.SourceDocument, raw: bytes) -> str:
        # write to a temp file so docling can ingest; content remains local
        import tempfile

        suffix = _suffix_for(source.media_type)
        fd, path = tempfile.mkstemp(suffix=suffix)
        with open(fd, "wb") as fh:
            fh.write(raw)
        return path

    # ---- safe fallback parser (always available) ----
    def _parse_fallback(
        self,
        source: schemas.SourceDocument,
        raw: bytes,
        config_hash: str,
        engine_engines: list[str],
    ) -> ParseOutcome:
        text = _decode_text(raw, source.media_type)
        blocks = _split_blocks(text)
        doc = {
            "schema": "knovaryn-canonical/1.0",
            "source_document_id": source.id,
            "parser": "fallback-text",
            "parser_version": "1",
            "config_hash": config_hash,
            "format": source.media_type,
            "blocks": blocks,
            "pages": [],
        }
        markdown = _blocks_to_markdown(blocks)
        plain = _strip_markdown(markdown)
        pages = max(source.page_or_sheet_count or 1, 1)
        diagnostics = {
            "parser": "fallback-text",
            "parser_version": "1",
            "note": "Docling extra not installed; used safe text fallback parser",
            "page_count": pages,
            "text_chars": len(plain),
            "heading_count": sum(1 for b in blocks if b["type"] == "heading"),
            "table_count": sum(1 for b in blocks if b["type"] == "table_cell"),
            "blank_or_low_text": len(plain) < 20,
            "ocr_engines": engine_engines,
        }
        return ParseOutcome(
            canonical_json=doc,
            markdown=markdown,
            plain_text=plain,
            diagnostics=diagnostics,
            parser_name="fallback-text",
            parser_version="1",
            pages=pages,
            used_docling=False,
            cleanup="n/a (fallback)",
        )

    def should_recycle(self) -> bool:
        return self._parses_this_worker >= self.recycle_documents


def _suffix_for(media_type: str) -> str:
    return {
        "application/pdf": ".pdf",
        "text/markdown": ".md",
        "text/plain": ".txt",
        "text/html": ".html",
        "text/xml": ".xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    }.get(media_type, ".txt")


def _decode_text(raw: bytes, media_type: str) -> str:
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s{0,3}[-*+]\s+(.*)$")
_NUM = re.compile(r"^\s{0,3}\d+[.)]\s+(.*)$")


def _split_blocks(text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    lines = text.splitlines()
    para: list[str] = []
    heading_path: list[str] = []

    def flush() -> None:
        nonlocal para
        if para:
            content = " ".join(x.strip() for x in para if x.strip())
            if content:
                blocks.append(
                    {"type": "paragraph", "text": content, "heading_path": list(heading_path)}
                )
            para = []

    for line in lines:
        h = _HEADING.match(line)
        if h:
            flush()
            level = len(h.group(1))
            heading_text = h.group(2).strip()
            # maintain a heading path by level
            heading_path = heading_path[: level - 1] + [heading_text]
            blocks.append(
                {
                    "type": "heading",
                    "level": level,
                    "text": heading_text,
                    "heading_path": list(heading_path),
                }
            )
            continue
        b = _BULLET.match(line)
        if b:
            flush()
            blocks.append(
                {
                    "type": "list_item",
                    "text": b.group(1).strip(),
                    "heading_path": list(heading_path),
                }
            )
            continue
        n = _NUM.match(line)
        if n:
            flush()
            blocks.append(
                {
                    "type": "list_item",
                    "text": n.group(1).strip(),
                    "heading_path": list(heading_path),
                }
            )
            continue
        if line.strip() == "":
            flush()
            continue
        para.append(line)
    flush()
    if not blocks and text.strip():
        blocks.append({"type": "paragraph", "text": text.strip(), "heading_path": []})
    return blocks


def _blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
    out: list[str] = []
    for b in blocks:
        t = b["type"]
        if t == "heading":
            out.append("#" * int(b.get("level", 1)) + " " + b["text"])
        elif t == "list_item":
            out.append("- " + b["text"])
        else:
            out.append(b["text"])
    return "\n\n".join(out)


def _strip_markdown(md: str) -> str:
    md = re.sub(r"`{1,3}", "", md)
    md = re.sub(r"[*_~>{}\[\]()#]", "", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()
