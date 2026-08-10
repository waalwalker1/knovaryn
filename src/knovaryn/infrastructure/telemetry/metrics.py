"""Metrics (spec §22.2).

Lightweight, dependency-free counters and gauges that back the observability
surface. Uses :class:`collections.Counter` internally so it is trivially
thread/async-safe for aggregate reporting and requires no external metric
backend to run the offline demo. A small Prometheus-style text renderer is
provided for the metrics endpoint.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetricsRegistry:
    """Counters + gauges keyed by dotted name, with optional label dicts."""

    counters: Counter = field(default_factory=Counter)
    gauges: dict[str, float] = field(default_factory=dict)
    histograms: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def inc(self, name: str, amount: int = 1, labels: dict[str, str] | None = None) -> None:
        key = _key(name, labels)
        self.counters[key] += amount

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        self.gauges[_key(name, labels)] = value

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        self.histograms[_key(name, labels)].append(value)

    def snapshot(self) -> dict[str, Any]:
        return {
            "counters": dict(self.counters),
            "gauges": dict(self.gauges),
            "histograms": {
                k: {
                    "count": len(v),
                    "sum": round(sum(v), 4),
                    "mean": round(sum(v) / len(v), 4) if v else 0.0,
                }
                for k, v in self.histograms.items()
            },
        }

    def render_prometheus(self) -> str:
        lines: list[str] = []
        for key, count in sorted(self.counters.items()):
            lines.append(f"# TYPE {key} counter")
            lines.append(f"{key} {count}")
        for key, gauge in sorted(self.gauges.items()):
            lines.append(f"# TYPE {key} gauge")
            lines.append(f"{key} {gauge}")
        return "\n".join(lines) + "\n"


def _key(name: str, labels: dict[str, str] | None) -> str:
    if not labels:
        return name
    joined = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f"{name}{{{joined}}}"


# Process-wide default registry.
_REGISTRY = MetricsRegistry()


def get_registry() -> MetricsRegistry:
    return _REGISTRY


class Timer:
    """Context manager that observes elapsed seconds into a histogram."""

    def __init__(
        self, registry: MetricsRegistry, name: str, labels: dict[str, str] | None = None
    ) -> None:
        self._registry = registry
        self._name = name
        self._labels = labels
        self._start = 0.0

    def __enter__(self) -> Timer:
        self._start = time.monotonic()
        return self

    def __exit__(self, *exc: Any) -> None:
        elapsed = time.monotonic() - self._start
        self._registry.observe(self._name, elapsed, self._labels)


__all__ = ["MetricsRegistry", "get_registry", "Timer"]
