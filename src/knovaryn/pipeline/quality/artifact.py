"""Artifact diagnostics and review (spec §14.3, §14.4).

Appraise a candidate/example for superficial artifacts (length, refusal,
formatting, injection), produce structured diagnostics, and drive quarantine
decisions. Deterministic heuristics; no model dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...domain.policies import (
    approximate_tokens,
    check_length_band,
    detect_injection_patterns,
    preference_is_trivially_separable,
)
from ...domain.schemas import Topology, TrainingExample


@dataclass
class ArtifactDiagnostic:
    example_id: str
    topology: str
    diagnostics: dict[str, Any] = field(default_factory=dict)
    injection_flags: list[str] = field(default_factory=list)
    artifact_resistance: float = 1.0  # 1 = clean, lower = artifact present
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "example_id": self.example_id,
            "topology": self.topology,
            "diagnostics": self.diagnostics,
            "injection_flags": self.injection_flags,
            "artifact_resistance": self.artifact_resistance,
            "reasons": self.reasons,
        }


def diagnose_example(example: TrainingExample) -> ArtifactDiagnostic:
    diag = ArtifactDiagnostic(example_id=example.id, topology=example.topology.value)
    reasons: list[str] = []
    resistance = 1.0

    chosen = _assistant_text(example)
    prompt = _prompt_text(example)

    diag.diagnostics["chosen_tokens"] = approximate_tokens(chosen)
    diag.diagnostics["prompt_tokens"] = approximate_tokens(prompt)

    # injection markers in user-visible content
    all_text = chosen + "\n" + prompt
    diag.injection_flags = detect_injection_patterns(all_text)
    if diag.injection_flags:
        resistance -= 0.4
        reasons.append("injection_marker")

    if example.topology == Topology.preference:
        chosen_a, rejected_a = _preference_texts(example)
        ok, ratio = check_length_band(chosen_a, rejected_a)
        diag.diagnostics["chosen_rejected_ratio"] = round(ratio, 3)
        if not ok:
            reasons.append("length_band_violation")
            resistance -= 0.2
        trivial, _ = preference_is_trivially_separable(chosen_a, rejected_a)
        if trivial:
            reasons.append("trivial_separation")
            resistance -= 0.3

    if example.topology == Topology.sft and not chosen.strip():
        reasons.append("empty_assistant")
        resistance -= 0.5

    # refusal artifacts
    low = chosen.lower()
    if any(w in low for w in ("cannot answer", "not available", "cannot determine")):
        diag.diagnostics["refusal_present"] = True
        if not detect_injection_patterns(prompt):
            # legitimate refusal is fine only when genuinely unanswerable
            if _prompt_text(example) and len(example.source_span_ids) > 0:
                reasons.append("possible_false_refusal")
                resistance -= 0.2

    diag.reasons = reasons
    diag.artifact_resistance = max(0.0, round(resistance, 3))
    return diag


def _assistant_text(ex: TrainingExample) -> str:
    msgs = ex.chosen_messages or ex.prompt_messages
    for m in msgs:
        if m.role == "assistant":
            return m.content
    return ""


def _prompt_text(ex: TrainingExample) -> str:
    parts = [m.content for m in ex.prompt_messages + ex.chosen_messages + ex.rejected_messages if m.role in ("user", "system")]
    return " ".join(parts)


def _preference_texts(ex: TrainingExample) -> tuple[str, str]:
    chosen = "".join(m.content for m in ex.chosen_messages if m.role == "assistant")
    rejected = "".join(m.content for m in ex.rejected_messages if m.role == "assistant")
    return chosen, rejected
