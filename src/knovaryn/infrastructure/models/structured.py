"""Structured-output strategy (spec §11.4).

Encodes how a provider's structured-output capability is requested, and falls
back gracefully to JSON-in-prompt when a model does not advertise native
structured output. Never fabricates provider capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .capabilities import Capability, capability_set


@dataclass
class StructuredOutputPlan:
    mode: str  # "native_jsonschema" | "json_in_prompt" | "constrained_decoding"
    schema_hash: str = ""
    note: str = ""


def plan_structured_output(
    *,
    supported: bool,
    schema_hash: str,
    prefer_native: bool = True,
) -> StructuredOutputPlan:
    """Choose a structured-output strategy based on advertised capability."""
    if supported and prefer_native:
        return StructuredOutputPlan(mode="native_jsonschema", schema_hash=schema_hash, note="provider advertises native json_schema")
    if supported:
        return StructuredOutputPlan(mode="constrained_decoding", schema_hash=schema_hash, note="provider advertises constrained decoding")
    return StructuredOutputPlan(
        mode="json_in_prompt",
        schema_hash=schema_hash,
        note="provider does not advertise native structured output; requesting JSON in prompt",
    )


def structured_output_required_capabilities() -> set[Capability]:
    return capability_set(structured_output=True)
