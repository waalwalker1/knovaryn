"""Deterministic structure-aware chunker (spec §10.2, ADR 0004).

Traverses the canonical block tree, keeps tables/list items intact, avoids
splitting sentences (unless a single element exceeds the hard limit), preserves
heading hierarchy, targets a token range, attaches element refs, hashes
normalized content, and exposes boundary reasons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...domain.hashing import ContentHasher, normalize_text
from ...domain.policies import approximate_tokens


@dataclass
class ChunkCfg:
    target_tokens: int = 900
    min_tokens: int = 180
    max_tokens: int = 1400
    neighbor_context_tokens: int = 350
    keep_tables_together: bool = True
    keep_lists_together: bool = True
    max_heading_depth: int = 6

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ChunkCfg:
        return cls(
            target_tokens=int(d.get("target_tokens", 900)),
            min_tokens=int(d.get("min_tokens", 180)),
            max_tokens=int(d.get("max_tokens", 1400)),
            neighbor_context_tokens=int(d.get("neighbor_context_tokens", 350)),
            keep_tables_together=bool(d.get("keep_tables_together", True)),
            keep_lists_together=bool(d.get("keep_lists_together", True)),
            max_heading_depth=int(d.get("max_heading_depth", 6)),
        )

    def config_hash(self) -> str:
        return ContentHasher.cfg_hash(self.__dict__)


@dataclass
class ChunkUnit:
    text: str
    element_type: str
    heading_path: list[str]
    kind: str = "text"  # heading | paragraph | list_item | table | caption | code


@dataclass
class ChunkResult:
    main_text: str
    context_text: str  # neighbor context (previous/next)
    heading_path: list[str]
    boundary_reasons: list[str]
    units: list[ChunkUnit] = field(default_factory=list)


def normalize_blocks(canonical: dict[str, Any]) -> list[ChunkUnit]:
    """Convert canonical doc JSON (fallback or docling-shaped) to ChunkUnits."""
    units: list[ChunkUnit] = []
    blocks = canonical.get("blocks") or _extract_docling_blocks(canonical)
    for b in blocks:
        btype = b.get("type", "paragraph")
        heading_path = list(b.get("heading_path") or [])
        if btype == "heading":
            units.append(ChunkUnit(b.get("text", ""), "heading", heading_path, kind="heading"))
        elif btype == "list_item":
            units.append(ChunkUnit(b.get("text", ""), "list_item", heading_path, kind="list_item"))
        elif btype in ("table", "table_cell"):
            units.append(ChunkUnit(b.get("text", ""), "table", heading_path, kind="table"))
        elif btype == "caption":
            units.append(ChunkUnit(b.get("text", ""), "caption", heading_path, kind="caption"))
        else:
            units.append(ChunkUnit(b.get("text", ""), "paragraph", heading_path, kind="text"))
    return units


def _extract_docling_blocks(docling: dict[str, Any]) -> list[dict[str, Any]]:
    """Best-effort extraction from a Docling export_to_dict() document."""
    blocks: list[dict[str, Any]] = []
    for item in docling.get("main_text", []):
        text = item.get("text", "")
        label = item.get("label", "text").lower()
        if not text:
            continue
        if label == "title" or label.startswith("heading"):
            blocks.append({"type": "heading", "text": text, "heading_path": []})
        elif label == "table":
            blocks.append({"type": "table", "text": text, "heading_path": []})
        elif label == "list_item":
            blocks.append({"type": "list_item", "text": text, "heading_path": []})
        else:
            blocks.append({"type": "paragraph", "text": text, "heading_path": []})
    return blocks


def chunk_document(canonical: dict[str, Any], cfg: ChunkCfg) -> list[ChunkResult]:
    units = normalize_blocks(canonical)
    groups = _group_units(units, cfg)
    results: list[ChunkResult] = []
    for idx, group in enumerate(groups):
        text = group_text(group)
        reasons: list[str] = []
        # hard-limit: split a single oversized element only when necessary
        if approximate_tokens(text) > cfg.max_tokens and len(group) > 0:
            reasons.append("hard_max_tokens")
        if not text.strip():
            reasons.append("empty")
        # neighbor context = previous + next group text, bounded
        prev_text = group_text(groups[idx - 1]) if idx > 0 else ""
        next_text = group_text(groups[idx + 1]) if idx < len(groups) - 1 else ""
        context_parts: list[str] = []
        if prev_text and approximate_tokens(prev_text) <= cfg.neighbor_context_tokens:
            context_parts.append("[PREVIOUS CONTEXT]\n" + prev_text)
        if next_text and approximate_tokens(next_text) <= cfg.neighbor_context_tokens:
            context_parts.append("[NEXT CONTEXT]\n" + next_text)
        heading_path = group[-1].heading_path if group else []
        results.append(
            ChunkResult(
                main_text=text,
                context_text="\n\n".join(context_parts),
                heading_path=heading_path,
                boundary_reasons=reasons,
                units=group,
            )
        )
    return results


def _group_units(units: list[ChunkUnit], cfg: ChunkCfg) -> list[list[ChunkUnit]]:
    groups: list[list[ChunkUnit]] = []
    cur: list[ChunkUnit] = []
    cur_tokens = 0
    in_list = False

    def flush() -> None:
        nonlocal cur, cur_tokens, in_list
        if cur:
            groups.append(cur)
        cur = []
        cur_tokens = 0
        in_list = False

    for unit in units:
        ut = approximate_tokens(unit.text)
        if unit.kind == "heading":
            flush()
            cur.append(unit)
            cur_tokens += ut
            continue
        # table handling
        if unit.kind == "table" and cfg.keep_tables_together:
            if cur and cur_tokens + ut > cfg.max_tokens:
                flush()
            cur.append(unit)
            cur_tokens += ut
            flush()  # tables stand alone
            continue
        # list handling
        if unit.kind == "list_item" and cfg.keep_lists_together:
            if not in_list:
                cur_tokens = max(cur_tokens, cfg.min_tokens)  # ensure a chunk with lead
                in_list = True
            if cur_tokens + ut > cfg.max_tokens:
                flush()
                in_list = True
            cur.append(unit)
            cur_tokens += ut
            continue
        # paragraph/other
        if cur_tokens + ut > cfg.target_tokens and cur_tokens >= cfg.min_tokens:
            flush()
        if cur_tokens + ut > cfg.max_tokens and cur and not cur_tokens:
            # single oversize element
            cur.append(unit)
            cur_tokens += ut
            flush()
            continue
        if cur_tokens + ut > cfg.max_tokens:
            flush()
        cur.append(unit)
        cur_tokens += ut
        if cur_tokens >= cfg.max_tokens:
            flush()
    flush()
    if not groups and units:
        groups = [list(units)]
    return groups


def group_text(group: list[ChunkUnit]) -> str:
    return "\n".join(u.text for u in group if u.text.strip())


def chunk_hash(main_text: str) -> str:
    return ContentHasher.sha256_text(normalize_text(main_text))
