"""Structured-output schemas and local validation (spec §11.5 / WP D2).

Every generation topology has a real Pydantic output schema. The provider
output contract is the canonical candidate body (task family, messages,
evidence, answerability, …) — never the lineage fields (chunk id, source
document id, group id, split), which the generator stamps itself. We render
the Pydantic schema to JSON Schema to send to providers, and re-validate every
provider response locally against the same schema, so a malformed or
non-conforming response is caught at the pipeline boundary rather than
silently default-filled.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..domain.errors import ProviderError
from ..domain.schemas import (
    GeneratedEvaluationCandidate,
    GeneratedKTOCandidate,
    GeneratedPreferenceCandidate,
    GeneratedSFTCandidate,
)

# topology -> candidate schema whose body the provider must satisfy
_GeneratedModel = (
    type[GeneratedSFTCandidate]
    | type[GeneratedPreferenceCandidate]
    | type[GeneratedKTOCandidate]
    | type[GeneratedEvaluationCandidate]
)
_TOPOLOGY_MODEL: dict[str, _GeneratedModel] = {
    "sft": GeneratedSFTCandidate,
    "preference": GeneratedPreferenceCandidate,
    "kto": GeneratedKTOCandidate,
    "evaluation": GeneratedEvaluationCandidate,
}

# lineage fields stamped by the generator, never produced by the model
_LINEAGE_FIELDS = {"chunk_id", "source_document_id", "source_group_id", "split", "topology"}


def _topology_model(topology: str) -> _GeneratedModel:
    model = _TOPOLOGY_MODEL.get(topology)
    if model is None:
        raise ProviderError(f"unknown topology {topology}", retryable=False)
    return model


def supported_topologies() -> list[str]:
    return list(_TOPOLOGY_MODEL)


def generation_output_schema(topology: str) -> dict[str, Any]:
    """Render the JSON Schema a provider must satisfy for this topology.

    Lineage fields are stripped from ``properties`` so the wire contract never
    asks the model to emit them; ``required`` already excludes them because they
    carry defaults, so the schema is a faithful model-output contract.
    """
    model = _topology_model(topology)
    schema = model.model_json_schema()
    schema = dict(schema)
    props = dict(schema.get("properties", {}))
    for f in _LINEAGE_FIELDS:
        props.pop(f, None)
    schema["properties"] = props
    schema["required"] = [f for f in schema.get("required", []) if f not in _LINEAGE_FIELDS]
    return schema


def schema_hash_for(topology: str) -> str:
    """Stable content hash of the topology's output schema.

    Feed this to the gateway as the schema hash: two runs of the same schema
    share a hash (audit + dedupe), and any change to the schema changes it.
    """
    schema = generation_output_schema(topology)
    raw = json.dumps(schema, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "schema:" + hashlib.sha256(raw).hexdigest()[:16]


def encode_schema_for_wire(topology: str) -> str:
    """Compact JSON string of the output schema, for embedding in a prompt."""
    return json.dumps(generation_output_schema(topology), sort_keys=True, default=str)


def validate_generation_output(topology: str, body: dict[str, Any]) -> list[str]:
    """Locally validate a provider body against the topology schema.

    Returns a list of reason codes; empty means schema-valid. Never mutates
    ``body``. Raises ProviderError on unknown topology.
    """
    model = _topology_model(topology)
    codes: list[str] = []
    try:
        model.model_validate(body)
    except Exception as exc:  # noqa: BLE001 - pydantic ValidationError
        codes.append(f"schema::{type(exc).__name__.lower()}")
    return codes
