"""Docling adapter + fallback parser (spec §9, ADR 0003).

When the ``docling`` extra is installed, uses real Docling via
``DoclingResourceGuard`` and persists the DoclingDocument JSON as the canonical
artifact (Markdown/plain text are derivatives). When Docling is not installed,
degrades to a safe, structurally-faithful fallback parser so intake, chunking,
generation, and the offline demo still work. Never claims error-free extraction.

Resource safety (spec §2.4 / WP G5):

* the temporary file written for Docling is always unlinked in ``finally``;
* ``DoclingResourceGuard.persist_and_release`` runs after extraction so backing
  resources are released (public close / feature-detected unload / drop+gc);
* OCR / accelerator / thread policy from config are applied version-guarded;
* binary blobs that fall back to the text parser are **quarantined**, never
  decoded to garbage Latin-1 text.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
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
    quarantined: bool = False


@dataclass
class _DoclingSession:
    """Everything needed to finalize (persist + release) a live Docling result.

    Kept across the ``to_thread`` boundary so the heavy conversion runs off the
    event loop; ``persist_and_release`` is then invoked from the async side.
    """

    guard: DoclingResourceGuard
    canonical_json: dict[str, Any]
    markdown: str
    plain: str
    pages: int
    parser_version: str


_BINARY_MEDIA_TYPES = {
    "application/pdf",
    "application/zip",
    "application/epub+zip",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class DoclingAdapter:
    """Version-aware parser. Validates configured options at startup."""

    def __init__(
        self,
        *,
        ids: IdGenerator,
        ocr_profile: OCRProfile | None = None,
        recycle_documents: int = 25,
        store: Any | None = None,
    ) -> None:
        self._ids = ids
        self.ocr = ocr_profile or OCRProfile()
        self.recycle_documents = recycle_documents
        self.store = store
        self._parses_this_worker = 0
        self._persisted_artifact_id: str | None = None
        self._validate_options()

    def _validate_options(self) -> None:
        if self.ocr.mode not in ("off", "auto", "on", "force_engine"):
            raise ConfigurationError(f"invalid ocr_mode: {self.ocr.mode!r}")

    async def parse(
        self, source: schemas.SourceDocument, raw: bytes, *, config: dict[str, Any]
    ) -> ParseOutcome:
        self._parses_this_worker += 1
        engine_engines = detect_available_ocr_engines()
        config_hash = ContentHasher.cfg_hash(config)

        if docling_available():
            try:
                session = await asyncio.to_thread(
                    self._convert_docling, source, raw, config, config_hash, engine_engines
                )
                return await self._finalize_docling(session)
            except Exception as exc:  # noqa: BLE001 - fall back safely
                log.warning("docling parse failed (%s); falling back to safe parser", exc)
        # Safe fallback parser
        return self._parse_fallback(source, raw, config_hash, engine_engines)

    # ---- real docling (opt-in) ----
    def _build_converter(self, config: dict[str, Any]) -> Any:
        """Build the Docling DocumentConverter from OCR/accelerator/thread policy.

        Docling options differ across minor versions, so feature-detect each
        keyword argument rather than assuming a fixed signature. ``None`` /
        ``"auto"`` values are omitted so Docling falls back to its own default.
        """
        from docling.document_converter import DocumentConverter

        kwargs: dict[str, Any] = {}

        # version-guarded pipeline options
        pipeline = getattr(DocumentConverter, "PIPELINE_TYPES", None)
        if pipeline is None:
            import docling

            opt = {}
            for attr in ("pipeline_options", "pipeline_extra_options"):
                if hasattr(docling, attr):
                    try:
                        candidate = getattr(docling, attr)
                        if callable(candidate):
                            candidate = candidate()
                        opt[attr] = candidate
                    except Exception:  # noqa: BLE001
                        continue
            if opt:
                kwargs.update(opt)

        # OCR mode
        ocr_mode = config.get("ocr_mode") or self.ocr.mode
        if ocr_mode not in (None, "auto"):
            detect = getattr(pipeline, "detect_options", None) if pipeline else None
            if detect is not None:
                try:
                    opts = detect()
                    if ocr_mode not in ("off", "on"):
                        for p in (
                            "use_ocr",
                            "use_tableformer",
                            "use_docstruct",
                            "ocr_mode",
                            "ocr_engine",
                        ):
                            if hasattr(opts, p):
                                try:
                                    setattr(opts, p, ocr_mode == "on")
                                except Exception:  # noqa: BLE001
                                    continue
                    kwargs["pipeline_options"] = opts
                except Exception:  # noqa: BLE001
                    log.debug("could not build docling OCR options (version feature-detect)")

        # threading / accelerator hints, guarded
        for key in ("threads", "accelerator"):
            if config.get(key) not in (None, "auto"):
                kwargs[key] = config[key]

        return DocumentConverter(**kwargs)

    def _convert_docling(
        self,
        source: schemas.SourceDocument,
        raw: bytes,
        config: dict[str, Any],
        config_hash: str,
        engine_engines: list[str],
    ) -> _DoclingSession:
        converter = self._build_converter(config)
        path = self._bytes_to_path(source, raw)
        try:
            conv_result = converter.convert(path)
        finally:
            # clean up the temp file whether conversion succeeds or throws
            with contextlib.suppress(OSError):
                os.unlink(path)

        guard = DoclingResourceGuard(conv_result)
        docling_json = conv_result.document.export_to_dict()
        markdown = ""
        try:
            markdown = conv_result.document.export_to_markdown()
        except Exception:  # noqa: BLE001
            markdown = ""
        plain = _strip_markdown(markdown)
        pages = len(getattr(conv_result.document, "pages", None) or [])
        parser_version = str(getattr(conv_result.document, "format_version", "unknown"))
        return _DoclingSession(
            guard=guard,
            canonical_json=docling_json,
            markdown=markdown,
            plain=plain,
            pages=pages,
            parser_version=parser_version,
        )

    async def _finalize_docling(self, session: _DoclingSession) -> ParseOutcome:
        """Persist the canonical JSON then release Docling backing resources (WP G5)."""
        guard = session.guard
        cleanup = None
        try:
            cleanup = await guard.persist_and_release(self._persist_docling_json)
        except Exception as exc:  # noqa: BLE001
            log.warning("docling finalize/release failed: %s", exc)
        diagnostics = {
            "parser": "docling",
            "parser_version": session.parser_version,
            "page_count": session.pages,
            "text_chars": len(session.plain),
            "persisted_artifact_id": self._persisted_artifact_id,
            "cleanup_path": cleanup.api_used if cleanup else "unreleased",
        }
        return ParseOutcome(
            canonical_json=session.canonical_json,
            markdown=session.markdown,
            plain_text=session.plain,
            diagnostics=diagnostics,
            parser_name="docling",
            parser_version=session.parser_version,
            pages=session.pages,
            used_docling=True,
            cleanup=(cleanup.api_used if cleanup else "unreleased"),
        )

    async def _persist_docling_json(self, result: Any) -> None:
        """Persist the canonical DoclingDocument JSON as an immutable artifact.

        Called by ``DoclingResourceGuard.persist_and_release`` before backing
        resources are released. When no artifact store is configured the JSON is
        held only in memory (recorded as such) — still released, never leaked.
        """
        try:
            docling_json = result.document.export_to_dict()
            payload = json.dumps(docling_json, ensure_ascii=False).encode("utf-8")
            self._persisted_artifact_id = None
            if self.store is not None:
                manifest = await self.store.put(
                    payload,
                    media_type="application/json",
                    producer={"component": "docling", "component_version": "1"},
                    privacy="restricted",
                )
                self._persisted_artifact_id = manifest.get("artifact_id")
        except Exception as exc:  # noqa: BLE001
            log.warning("could not persist docling canonical JSON: %s", exc)
            self._persisted_artifact_id = None

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
        quarantine = _quarantine_reason(source.media_type, raw)
        if quarantine:
            return self._quarantine_outcome(
                source, raw, config_hash, engine_engines, quarantine
            )
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

    def _quarantine_outcome(
        self,
        source: schemas.SourceDocument,
        raw: bytes,
        config_hash: str,
        engine_engines: list[str],
        reason: str,
    ) -> ParseOutcome:
        """Return a minimal failed outcome for an unparseable binary (WP G5).

        The caller sets ``ExtractionStatus.failed`` from ``outcome.quarantined``.
        No garbage Latin-1 text is produced.
        """
        doc = {
            "schema": "knovaryn-canonical/1.0",
            "source_document_id": source.id,
            "parser": "quarantined",
            "parser_version": "1",
            "config_hash": config_hash,
            "format": source.media_type,
            "blocks": [],
            "pages": [],
        }
        diagnostics = {
            "parser": "quarantined",
            "parser_version": "1",
            "quarantined": True,
            "reason": reason,
            "media_type": source.media_type,
            "byte_size": len(raw),
            "text_chars": 0,
            "ocr_engines": engine_engines,
        }
        return ParseOutcome(
            canonical_json=doc,
            markdown="",
            plain_text="",
            diagnostics=diagnostics,
            parser_name="quarantined",
            parser_version="1",
            pages=0,
            used_docling=False,
            cleanup="n/a (fallback)",
            quarantined=True,
        )

    def should_recycle(self) -> bool:
        # containment hook: worker orchestration may call this to recycle the
        # process after ``recycle_documents`` parses (bounded memory growth).
        return self._parses_this_worker >= self.recycle_documents


def _quarantine_reason(media_type: str, raw: bytes) -> str | None:
    """Return a quarantine reason for a binary fallback, or None if parseable.

    A binary media type handled by the text fallback is only accepted as text if
    its bytes are clean UTF-8 with no NUL / control bytes; anything else is
    quarantined rather than downgraded to lossy Latin-1.
    """
    is_binary = media_type in _BINARY_MEDIA_TYPES or media_type.startswith("image/")
    if not is_binary:
        return None
    if b"\x00" in raw:
        return f"binary source of type {media_type} contained non-text data"
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return f"binary source of type {media_type} could not be parsed as text"
    return None


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
