"""Model-call fingerprinting (spec §11.5).

Re-exports the canonical call fingerprint from the domain hashing module so the
model-gateway package exposes a single stable entry point. The fingerprint
covers messages, prompt-template version, model, sampling, schema hash, and
source hashes — so a resumed job never repays for an accepted call.
"""

from __future__ import annotations

from typing import Any

from ...domain.hashing import fingerprint


def make_call_fingerprint(
    *,
    messages: list[dict[str, Any]],
    prompt_template_version: str | None,
    model: str,
    sampling: dict[str, Any],
    schema_hash: str | None,
    source_hashes: list[str],
) -> str:
    return fingerprint(
        messages=messages,
        prompt_template_version=prompt_template_version,
        model=model,
        sampling=sampling,
        schema_hash=schema_hash,
        source_hashes=source_hashes,
    )


__all__ = ["fingerprint", "make_call_fingerprint"]
