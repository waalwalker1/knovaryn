"""Multi-format dataset exporters (spec §15, WP H4).

Reuses the canonical :func:`~knovaryn.pipeline.export.exporters.example_row`
base from the JSONL exporter and renders each accepted example into a variety of
shareable training layouts (OpenAI chat, ShareGPT, Alpaca, TRL SFT/preference,
KTO, evaluation, HF layout). Every row keeps explicit, non-parsed lineage
fields (``source_document_ids`` / ``source_span_ids`` /
``generation_candidate_ids`` / ``content_hash``) so provenance stays traversable
without parsing display strings (contract rule 14 / A6), and order is
deterministic by example id.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any

from ...domain.schemas import TrainingExample
from .exporters import ExportResult, _atomic_write, _messages_json

SUPPORTED_FORMATS = frozenset(
    {
        "openai_chat",
        "sharegpt",
        "alpaca",
        "trl_sft",
        "trl_preference",
        "kto",
        "evaluation",
        "huggingface_layout",
    }
)

MEDIA_TYPES = dict.fromkeys(SUPPORTED_FORMATS, "application/jsonl")
MEDIA_TYPES["jsonl"] = "application/jsonl"
MEDIA_TYPES["parquet"] = "application/octet-stream"


def _provenance(ex: TrainingExample) -> dict[str, Any]:
    return {
        "source_document_ids": ex.source_document_ids,
        "source_span_ids": ex.source_span_ids,
        "generation_candidate_ids": ex.generation_candidate_ids,
        "content_hash": ex.content_hash,
        "split": ex.split,
    }


def _sys(ex: TrainingExample) -> list[str]:
    return list(ex.system_messages)


def _prompt_text(ex: TrainingExample) -> str:
    parts: list[str] = []
    for m in ex.prompt_messages:
        parts.append(m.content)
    return "\n".join(x for x in parts if x)


def _chosen_text(ex: TrainingExample) -> str:
    return "\n".join(m.content for m in ex.chosen_messages if m.content)


def _rejected_text(ex: TrainingExample) -> str:
    return "\n".join(m.content for m in ex.rejected_messages if m.content)


def _openai_messages(ex: TrainingExample) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [{"role": "system", "content": s} for s in _sys(ex)]
    rows.extend(_messages_json(ex.prompt_messages + ex.chosen_messages))
    return rows


def row_openai_chat(ex: TrainingExample) -> dict[str, Any]:
    return {"messages": _openai_messages(ex), **_provenance(ex)}


def row_sharegpt(ex: TrainingExample) -> dict[str, Any]:
    conversations: list[dict[str, str]] = []
    for m in ex.prompt_messages + ex.chosen_messages:
        from_human = m.role in ("user", "system")
        conversations.append({"from": "human" if from_human else "gpt", "value": m.content})
    return {"conversations": conversations, **_provenance(ex)}


def row_alpaca(ex: TrainingExample) -> dict[str, Any]:
    lines = [m.content for m in ex.prompt_messages if m.role in ("user", "system")]
    instruction = lines[0] if lines else ""
    inp = "\n".join(lines[1:]) if len(lines) > 1 else ""
    return {
        "instruction": instruction,
        "input": inp,
        "output": _chosen_text(ex),
        **_provenance(ex),
    }


def row_trl_sft(ex: TrainingExample) -> dict[str, Any]:
    text = "\n".join(f"{m['role']}: {m['content']}" for m in _openai_messages(ex))
    return {"text": text, **_provenance(ex)}


def row_trl_preference(ex: TrainingExample) -> dict[str, Any]:
    return {
        "prompt": _prompt_text(ex),
        "chosen": _chosen_text(ex),
        "rejected": _rejected_text(ex),
        **_provenance(ex),
    }


def row_kto(ex: TrainingExample) -> dict[str, Any]:
    # KTO desirability derived from the canonical label/target, defaulting to
    # "good" for accepted chosen content (false never asserted eagerly; the
    # label is carried through from the canonical example when present).
    label = ex.label_or_target
    if label is None:
        label = True
    return {
        "prompt": _prompt_text(ex),
        "completion": _chosen_text(ex),
        "label": bool(label),
        **_provenance(ex),
    }


def row_evaluation(ex: TrainingExample) -> dict[str, Any]:
    return {
        "prompt": _prompt_text(ex),
        "reference_answer": _chosen_text(ex),
        **_provenance(ex),
    }


def row_huggingface_layout(ex: TrainingExample) -> dict[str, Any]:
    return {
        "messages": _openai_messages(ex),
        "topology": ex.topology.value,
        "quality_score": round(ex.quality_score, 4),
        **_provenance(ex),
    }


RowBuilder = Callable[[TrainingExample], dict[str, Any]]
_ROW_BUILDERS: dict[str, RowBuilder] = {
    "openai_chat": row_openai_chat,
    "sharegpt": row_sharegpt,
    "alpaca": row_alpaca,
    "trl_sft": row_trl_sft,
    "trl_preference": row_trl_preference,
    "kto": row_kto,
    "evaluation": row_evaluation,
    "huggingface_layout": row_huggingface_layout,
}


def example_row_for(ex: TrainingExample, fmt: str) -> dict[str, Any]:
    if fmt == "jsonl":
        from .exporters import example_row

        return example_row(ex)
    builder = _ROW_BUILDERS.get(fmt)
    if builder is None:
        raise ValueError(f"unsupported export format: {fmt!r}")
    return builder(ex)


def export_format(
    examples: Iterable[TrainingExample], format: str, *, path: str = ""
) -> ExportResult:
    """Serialize accepted examples in a supported format as JSONL.

    Each line is one JSONL record. Provenance + ``content_hash`` are always
    preserved so a format export can be re-traced to its sources (rule 13/14).
    """
    if format not in SUPPORTED_FORMATS and format not in ("jsonl",):
        raise ValueError(f"unsupported export format: {format!r}")

    rows = [example_row_for(ex, format) for ex in examples]
    lines = [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows]
    text = "\n".join(lines) + ("\n" if lines else "")
    data = text.encode("utf-8")

    from ...domain.hashing import ContentHasher

    sha = ContentHasher.sha256_text(text)
    if path:
        _atomic_write(path, data)
    return ExportResult(
        rows=len(lines), format=format, byte_size=len(data), sha256=sha, path=path, bytes=data
    )
