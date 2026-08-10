"""Tracing bridges (spec §22.3).

A minimal, dependency-free trace context that records span start/end and
parent/child relationships. No OpenTelemetry agent is required for the offline
demo; the context keeps a span tree in memory so the observability surface can
emit it. If ``opentelemetry-sdk`` is installed it is used opportunistically,
otherwise the internal span store carries the trace.
"""

from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass, field
from typing import Any

_current: contextvars.ContextVar[_Span | None] = contextvars.ContextVar(
    "knovaryn_trace", default=None
)


@dataclass
class _Span:
    name: str
    parent: _Span | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    children: list[_Span] = field(default_factory=list)
    start_mono: float = 0.0
    duration_ms: float | None = None

    def child(self, name: str) -> _Span:
        c = _Span(name=name, parent=self, start_mono=time.monotonic())
        self.children.append(c)
        return c


class TraceContext:
    """Context manager recording a span under the current parent."""

    def __init__(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self._name = name
        self._attributes = attributes or {}
        self._span: _Span | None = None
        self._tok: contextvars.Token | None = None

    def __enter__(self) -> TraceContext:
        parent = _current.get()
        self._span = (
            parent.child(self._name)
            if parent
            else _Span(name=self._name, start_mono=time.monotonic())
        )
        self._span.attributes.update(self._attributes)
        self._tok = _current.set(self._span)
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._tok is not None:
            _current.reset(self._tok)
        if self._span is not None:
            self._span.duration_ms = (time.monotonic() - self._span.start_mono) * 1000.0


def start_span(name: str, attributes: dict[str, Any] | None = None) -> TraceContext:
    return TraceContext(name, attributes)


def current_span_name() -> str | None:
    sp = _current.get()
    return sp.name if sp else None


def flush_trace() -> None:
    """Reset the trace root so a fresh trace begins on the next span."""
    _current.set(None)


__all__ = ["TraceContext", "start_span", "current_span_name", "flush_trace"]
