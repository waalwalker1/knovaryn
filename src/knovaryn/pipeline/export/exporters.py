"""Dataset exporters (spec §15).

Serialize accepted training examples into shareable formats: JSONL
(SFT chat format, preference chosen/rejected, KTO, evaluation) and optional
Parquet. Every row carries provenance + content hash. Deterministic ordering
by example id.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from ...domain.hashing import ContentHasher
from ...domain.schemas import Topology, TrainingExample


def _messages_json(messages) -> list[dict[str, Any]]:  # noqa: ANN001
    return [{"role": m.role, "content": m.content} for m in messages]


def example_to_sft_row(ex: TrainingExample) -> dict[str, Any]:
    msgs = _messages_json(ex.prompt_messages + ex.chosen_messages)
    # ensure a system prefix is included if configured
    sys_rows = [{"role": "system", "content": s} for s in ex.system_messages]
    return {
        "messages": sys_rows + msgs,
        "topology": ex.topology.value,
        "split": ex.split,
        "source_document_ids": ex.source_document_ids,
        "source_span_ids": ex.source_span_ids,
        "content_hash": ex.content_hash,
        "quality_score": round(ex.quality_score, 4),
    }


def example_to_preference_row(ex: TrainingExample) -> dict[str, Any]:
    return {
        "prompt": _messages_json(ex.prompt_messages),
        "chosen": _messages_json(ex.chosen_messages),
        "rejected": _messages_json(ex.rejected_messages),
        "topology": ex.topology.value,
        "split": ex.split,
        "source_document_ids": ex.source_document_ids,
        "content_hash": ex.content_hash,
        "quality_score": round(ex.quality_score, 4),
    }


def example_to_kto_row(ex: TrainingExample) -> dict[str, Any]:
    # For KTO the chosen/rejected encode desirability; emit messages + label
    messages = _messages_json(ex.prompt_messages + ex.chosen_messages)
    return {
        "messages": messages,
        "label": ex.label_or_target,
        "topology": ex.topology.value,
        "split": ex.split,
        "source_document_ids": ex.source_document_ids,
        "content_hash": ex.content_hash,
        "quality_score": round(ex.quality_score, 4),
    }


def example_row(ex: TrainingExample) -> dict[str, Any]:
    if ex.topology == Topology.preference:
        return example_to_preference_row(ex)
    if ex.topology == Topology.kto:
        return example_to_kto_row(ex)
    return example_to_sft_row(ex)


@dataclass
class ExportResult:
    rows: int
    format: str
    byte_size: int
    sha256: str
    path: str = ""
    bytes: bytes = b""


def export_jsonl(examples: Iterable[TrainingExample], *, path: str = "") -> ExportResult:
    """Write accepted examples as JSONL, one JSON object per line."""
    import tempfile

    lines: list[str] = []
    for ex in examples:
        lines.append(json.dumps(example_row(ex), ensure_ascii=False, sort_keys=True))
    text = "\n".join(lines) + ("\n" if lines else "")
    data = text.encode("utf-8")
    sha = ContentHasher.sha256_text(text)
    if path:
        _atomic_write(path, data)
    return ExportResult(rows=len(lines), format="jsonl", byte_size=len(data), sha256=sha, path=path, bytes=data)


def export_parquet(examples: Iterable[TrainingExample], *, path: str = "") -> ExportResult:
    """Optional Parquet export; requires the 'knovaryn[parquet]' extra."""
    import importlib.util

    if importlib.util.find_spec("pyarrow") is None and importlib.util.find_spec("pandas") is None:
        raise ImportError(
            "Parquet export requires the 'knovaryn[parquet]' extra (pyarrow/pandas). "
            "Install the extra or export JSONL instead."
        )
    import pandas as pd

    rows = [example_row(ex) for ex in examples]
    frame = pd.DataFrame(rows)
    if path:
        frame.to_parquet(path, index=False)
    # hash of canonical json for determinism
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True)
    sha = ContentHasher.sha256_text(canonical)
    import io

    buf = io.BytesIO()
    frame.to_parquet(buf, index=False)
    return ExportResult(rows=len(rows), format="parquet", byte_size=buf.getbuffer().nbytes, sha256=sha, path=path, bytes=buf.getvalue())


def _atomic_write(path: str, data: bytes) -> None:
    import os
    import tempfile

    dirpath = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=dirpath, prefix=".kny-export-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
