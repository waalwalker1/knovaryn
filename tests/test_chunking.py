"""Structure-aware chunking (spec §10.2)."""

from __future__ import annotations

from knovaryn.infrastructure.chunking.structure_aware import ChunkCfg, chunk_document


def _doc(text: str) -> dict:
    lines = text.split("\n")
    blocks = []
    path: list[str] = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("##"):
            path = [ln.lstrip("#").strip()]
            blocks.append({"type": "heading", "text": ln.lstrip("#").strip(), "heading_path": path})
        elif ln.startswith("- "):
            blocks.append({"type": "list_item", "text": ln[2:], "heading_path": list(path)})
        else:
            blocks.append({"type": "paragraph", "text": ln, "heading_path": list(path)})
    return {"schema": "knovaryn-canonical/1.0", "blocks": blocks}


def test_chunk_document_produces_chunks() -> None:
    text = "\n".join(
        [
            "# Doc",
            "## Intro",
            "This is the opening paragraph that explains the topic in sufficient detail.",
        ]
        + [
            f"## Section {i}\nParagraph {i} with a reasonable amount of "
            f"descriptive text for chunking."
            for i in range(5)
        ]
    )
    doc = _doc(text)
    cfg = ChunkCfg(target_tokens=60, min_tokens=10, max_tokens=200)
    chunks = chunk_document(doc, cfg)
    assert len(chunks) >= 1
    assert all(c.main_text for c in chunks)


def test_heading_path_preserved() -> None:
    doc = _doc("## Alpha\nSome text under Alpha.")
    cfg = ChunkCfg(target_tokens=50, min_tokens=5, max_tokens=300)
    chunks = chunk_document(doc, cfg)
    assert chunks
    assert any(c.heading_path for c in chunks)


def test_tables_kept_together() -> None:
    doc = {
        "schema": "knovaryn-canonical/1.0",
        "blocks": [
            {"type": "heading", "text": "T", "heading_path": ["T"]},
            {"type": "table", "text": "a|b\nc|d", "heading_path": ["T"]},
            {"type": "paragraph", "text": "after", "heading_path": ["T"]},
        ],
    }
    cfg = ChunkCfg(keep_tables_together=True, target_tokens=10, min_tokens=2, max_tokens=500)
    chunks = chunk_document(doc, cfg)
    joined = [c.main_text for c in chunks]
    assert any("a|b" in j for j in joined)
