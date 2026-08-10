"""Capability negotiation (spec §11.3).

A provider adapter declares/looks up capabilities; results are cached with a
TTL and can be overridden by an administrator. Capabilities are queried through
the gateway rather than assumed from provider names.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Capability(StrEnum):
    STRUCTURED_OUTPUT = "structured_json_schema"
    TOOL_USE = "tool_use"
    IMAGE_INPUT = "image_input"
    SEED = "seed"
    BATCH = "batch"
    USAGE_REPORTING = "usage_reporting"
    STREAMING = "streaming"


@dataclass
class ProviderCapabilities:
    structured_output: bool = False
    tool_use: bool = False
    image_input: bool = False
    seed: bool = False
    batch: bool = False
    usage_reporting: bool = True
    streaming: bool = True
    max_context_tokens: int | None = None
    max_output_tokens: int | None = None

    def supports(self, cap: Capability) -> bool:
        return getattr(self, cap.value, False)

    def as_dict(self) -> dict[str, Any]:
        return {
            Capability.STRUCTURED_OUTPUT.value: self.structured_output,
            Capability.TOOL_USE.value: self.tool_use,
            Capability.IMAGE_INPUT.value: self.image_input,
            Capability.SEED.value: self.seed,
            Capability.BATCH.value: self.batch,
            Capability.USAGE_REPORTING.value: self.usage_reporting,
            Capability.STREAMING.value: self.streaming,
        }


def capability_set(
    *,
    structured_output: bool = False,
    tool_use: bool = False,
    image_input: bool = False,
    seed: bool = False,
    batch: bool = False,
    usage_reporting: bool = True,
    streaming: bool = True,
    max_context_tokens: int | None = None,
    max_output_tokens: int | None = None,
) -> ProviderCapabilities:
    return ProviderCapabilities(
        structured_output=structured_output,
        tool_use=tool_use,
        image_input=image_input,
        seed=seed,
        batch=batch,
        usage_reporting=usage_reporting,
        streaming=streaming,
        max_context_tokens=max_context_tokens,
        max_output_tokens=max_output_tokens,
    )


@dataclass
class CapabilityCache:
    """TTL cache with administrative override."""

    ttl_s: int = 3600
    _store: dict[tuple[str, str], tuple[int, ProviderCapabilities]] = field(default_factory=dict)
    _overrides: dict[tuple[str, str], ProviderCapabilities] = field(default_factory=dict)

    def set_override(self, provider: str, model: str, caps: ProviderCapabilities) -> None:
        self._overrides[(provider, model)] = caps

    def clear_override(self, provider: str, model: str) -> None:
        self._overrides.pop((provider, model), None)

    def get(self, provider: str, model: str) -> ProviderCapabilities | None:
        key = (provider, model)
        if key in self._overrides:
            return self._overrides[key]
        if key not in self._store:
            return None
        stored_at, caps = self._store[key]
        if time.monotonic() - stored_at > self.ttl_s:
            return None
        return caps

    def set(self, provider: str, model: str, caps: ProviderCapabilities) -> None:
        self._store[(provider, model)] = (int(time.monotonic()), caps)
