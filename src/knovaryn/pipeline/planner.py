"""Dataset planner (spec §12.3).

Translates a DatasetPlan into concrete generation assignments across the
available chunks: how many candidates of each topology × task family ×
difficulty to generate, honoring proportions, refusal proportion, and
cross-document allowance. Purely deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.schemas import DatasetPlan, TaskFamily, Topology

_TOPOLOGIES = [Topology.sft, Topology.preference, Topology.kto, Topology.evaluation]
_DIFFICULTIES = ["basic", "intermediate", "advanced"]


@dataclass
class AssignmentSpec:
    topology: str
    task_family: str
    difficulty: str
    per_chunk: int


@dataclass
class PlanResult:
    specs: list[AssignmentSpec] = field(default_factory=list)
    total_expected_examples: int = 0
    distribution_matrix: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "specs": [vars(s) for s in self.specs],
            "total_expected_examples": self.total_expected_examples,
            "distribution_matrix": self.distribution_matrix,
        }


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values()) or 1.0
    return {k: v / total for k, v in weights.items()}


def plan(plan: DatasetPlan, *, chunk_count: int) -> PlanResult:
    families = _normalize(plan.effective_proportions())
    difficulty = _normalize(plan.difficulty_distribution or {"basic": 0.3, "intermediate": 0.5, "advanced": 0.2})
    topology_weights = _topology_weights(plan)

    out = PlanResult()
    for topology, topo_weight in topology_weights:
        for family, fam_weight in families.items():
            for diff, diff_weight in difficulty.items():
                # deterministic rounding: accumulate expected count
                count = int(round(chunk_count * topo_weight * fam_weight * diff_weight))
                if count <= 0:
                    continue
                out.specs.append(AssignmentSpec(topology=topology, task_family=family, difficulty=diff, per_chunk=count))
                out.distribution_matrix[f"{topology}/{family}/{diff}"] = count
    out.total_expected_examples = sum(s.per_chunk for s in out.specs)
    return out


def _topology_weights(plan: DatasetPlan) -> list[tuple[str, float]]:
    # Default: SFT-dominant with smaller preference/eval/KTO presence.
    # If the plan carries explicit topology proportions, honor them.
    explicit = plan.metadata.get("topology_proportions") if isinstance(plan.metadata, dict) else None
    _valid = [t.value for t in _TOPOLOGIES]
    if isinstance(explicit, dict) and explicit:
        weights = _normalize({k: v for k, v in explicit.items() if k in _valid})
    else:
        weights = {"sft": 0.6, "preference": 0.2, "kto": 0.1, "evaluation": 0.1}
    return [(t, weights.get(t, 0.0)) for t in _valid]
