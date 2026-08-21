"""Dataset planner (spec §12.3).

Translates a DatasetPlan into concrete generation assignments across the
available chunks: how many candidates of each topology × task family ×
difficulty to generate, honoring proportions, refusal proportion, and
cross-document allowance. Purely deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.schemas import DatasetPlan, Topology

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


def plan(
    plan: DatasetPlan,
    *,
    chunk_count: int,
    target_examples: int | None = None,
    budget: dict[str, float] | None = None,
) -> PlanResult:
    families = _normalize(plan.effective_proportions())
    difficulty = _normalize(
        plan.difficulty_distribution or {"basic": 0.3, "intermediate": 0.5, "advanced": 0.2}
    )
    topology_weights = _topology_weights(plan)

    out = PlanResult()

    # Budget cap (defect 4.4): maximum examples is a hard ceiling on the planned
    # total. A target above the budget is clamped down so generation stops short
    # of overruns rather than silently exceeding the documented cap.
    budget_cap: float | None = None
    if isinstance(budget, dict) and budget.get("maximum_examples") is not None:
        budget_cap = float(budget["maximum_examples"])
    if target_examples is not None and budget_cap is not None:
        target_examples = int(min(target_examples, budget_cap))

    for topology, topo_weight in topology_weights:
        for family, fam_weight in families.items():
            for diff, diff_weight in difficulty.items():
                if target_examples is not None:
                    # target-driven allocation: the cell's share of the target
                    # (a total across all chunks, consistent with how
                    # total_expected_examples sums the per-spec counts)
                    count = int(round(target_examples * topo_weight * fam_weight * diff_weight))
                else:
                    count = int(round(chunk_count * topo_weight * fam_weight * diff_weight))
                if count <= 0:
                    continue
                out.specs.append(
                    AssignmentSpec(
                        topology=topology, task_family=family, difficulty=diff, per_chunk=count
                    )
                )
                out.distribution_matrix[f"{topology}/{family}/{diff}"] = count
    out.total_expected_examples = sum(s.per_chunk for s in out.specs)
    return out


def _topology_weights(plan: DatasetPlan) -> list[tuple[str, float]]:
    # Default: SFT-dominant with smaller preference/eval/KTO presence.
    # If the plan carries explicit topology proportions, honor them.
    explicit = (
        plan.metadata.get("topology_proportions") if isinstance(plan.metadata, dict) else None
    )
    _valid = [t.value for t in _TOPOLOGIES]
    if isinstance(explicit, dict) and explicit:
        weights = _normalize({k: v for k, v in explicit.items() if k in _valid})
    else:
        weights = {"sft": 0.6, "preference": 0.2, "kto": 0.1, "evaluation": 0.1}
    return [(t, weights.get(t, 0.0)) for t in _valid]


@dataclass
class TopUpResult:
    """A top-up plan that fills a shortfall after validation, within budget."""

    shortfall: int = 0
    additional: int = 0
    capped_by_budget: bool = False
    specs: list[AssignmentSpec] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "shortfall": self.shortfall,
            "additional": self.additional,
            "capped_by_budget": self.capped_by_budget,
            "specs": [vars(s) for s in self.specs],
        }


def top_up_plan(
    plan_result: PlanResult,
    *,
    target_examples: int,
    validated_examples: int,
    budget: dict[str, float] | None = None,
) -> TopUpResult:
    """Compute a top-up plan to reach ``target_examples`` after validation.

    Validation drops examples below the quality bar; the generated count usually
    lands short of target. Top-up reuses the original composition (relative
    weights of each spec) to allocate the remaining slots, and honors the budget
    ``maximum_examples`` hard cap — declining to plan beyond it.
    """
    budget_cap: int | None = None
    if isinstance(budget, dict) and budget.get("maximum_examples") is not None:
        budget_cap = int(budget["maximum_examples"])

    previously_planned = plan_result.total_expected_examples
    shortfall = max(0, target_examples - validated_examples)
    if shortfall <= 0:
        return TopUpResult(shortfall=0, additional=0, capped_by_budget=False)

    # Respect the budget: we may only plan additional examples up to the cap.
    additional = shortfall
    capped = False
    if budget_cap is not None:
        # what we already generated + what we would add must stay under the cap
        room = max(0, budget_cap - previously_planned)
        if additional > room:
            additional = room
            capped = True
    if additional <= 0:
        return TopUpResult(shortfall=shortfall, additional=0, capped_by_budget=True, specs=[])

    # Allocate the shortfall across the existing compositions by their weight.
    total_weight = sum(s.per_chunk for s in plan_result.specs) or 1
    specs: list[AssignmentSpec] = []
    allocated = 0
    for s in plan_result.specs:
        share = int(round(additional * (s.per_chunk / total_weight)))
        if share <= 0:
            continue
        specs.append(
            AssignmentSpec(
                topology=s.topology,
                task_family=s.task_family,
                difficulty=s.difficulty,
                per_chunk=share,
            )
        )
        allocated += share
    return TopUpResult(
        shortfall=shortfall,
        additional=allocated,
        capped_by_budget=capped,
        specs=specs,
    )
