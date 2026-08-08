"""Prompt manifest (spec §12.7).

A durable record of exactly which prompt templates (name + version + rendered
inputs) produced each generated candidate, so any example can be audited back
to the prompt that generated it and re-rendered deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.hashing import ContentHasher


@dataclass
class PromptUsageRecord:
    candidate_id: str
    chunk_id: str
    task_family: str
    topology: str
    template_name: str
    template_version: str
    slots_hash: str
    messages_hash: str
    model: str
    prompt_fingerprint: str
    generated_at_note: str = ""


@dataclass
class PromptManifest:
    records: list[PromptUsageRecord] = field(default_factory=list)

    def add(self, rec: PromptUsageRecord) -> None:
        self.records.append(rec)

    def record_for(self, candidate_id: str) -> PromptUsageRecord | None:
        for rec in self.records:
            if rec.candidate_id == candidate_id:
                return rec
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": "1",
            "record_count": len(self.records),
            "records": [vars(r) for r in self.records],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PromptManifest":
        out = cls()
        for r in data.get("records", []):
            out.add(PromptUsageRecord(**r))
        return out

    def manifest_hash(self) -> str:
        return ContentHasher.cfg_hash(self.to_dict())


def build_prompt_usage_record(
    *,
    candidate_id: str,
    chunk_id: str,
    task_family: str,
    topology: str,
    template_name: str,
    template_version: str,
    slots: dict[str, Any],
    messages: list[dict[str, Any]],
    model: str,
) -> PromptUsageRecord:
    slots_hash = ContentHasher.sha256_text(ContentHasher.cfg_hash(slots))
    messages_hash = ContentHasher.sha256_text(ContentHasher.cfg_hash(messages))
    prompt_fingerprint = ContentHasher.sha256_text(
        f"{template_name}:{template_version}:{slots_hash}:{messages_hash}"
    )
    return PromptUsageRecord(
        candidate_id=candidate_id,
        chunk_id=chunk_id,
        task_family=task_family,
        topology=topology,
        template_name=template_name,
        template_version=template_version,
        slots_hash=slots_hash,
        messages_hash=messages_hash,
        model=model,
        prompt_fingerprint=prompt_fingerprint,
    )
