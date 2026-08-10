"""Prompt library (spec §12.4).

Versioned prompt templates for each task family × topology. Templates are
registered with a stable version string and produce ``(system, user)`` message
pairs with named slots. The library never interpolates model output; it only
renders the static scaffolding that the generator fills with evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..domain.schemas import TaskFamily


@dataclass(frozen=True)
class TemplateRef:
    name: str
    version: str
    task_family: str
    topology: str
    system_template: str
    user_template: str


_REGISTRY: dict[tuple[str, str], TemplateRef] = {}


def _register(t: TemplateRef) -> None:
    _REGISTRY[(t.task_family, t.topology)] = t


def _base_system() -> str:
    return (
        "You are a careful, precise domain assistant. Base every answer strictly "
        "on the provided source material. Do not add information not supported "
        "by the material. If the material does not contain the answer, say so "
        " explicitly rather than guessing."
    )


def _build_registry() -> None:
    for tf in TaskFamily:
        # SFT
        _register(
            TemplateRef(
                name=f"{tf.value}/sft",
                version="1",
                task_family=tf.value,
                topology="sft",
                system_template=_base_system(),
                user_template=(
                    "Given the following source material, answer the question.\n\n"
                    "SOURCE MATERIAL:\n{source_text}\n\nQUESTION:\n{question}\n\n"
                    "Provide a concise, well-grounded answer that cites the relevant material."
                ),
            )
        )
        # Preference
        _register(
            TemplateRef(
                name=f"{tf.value}/preference",
                version="1",
                task_family=tf.value,
                topology="preference",
                system_template=_base_system(),
                user_template=(
                    "Below are two candidate answers to the same question. Choose the more "
                    "accurate, complete, and faithful-to-source answer.\n\n"
                    "SOURCE MATERIAL:\n{source_text}\n\nQUESTION:\n{question}\n\n"
                    "Candidate A:\n{candidate_a}\n\nCandidate B:\n{candidate_b}\n\n"
                    "Provide your judgment as A or B followed by a one-line reason."
                ),
            )
        )
        # KTO
        _register(
            TemplateRef(
                name=f"{tf.value}/kto",
                version="1",
                task_family=tf.value,
                topology="kto",
                system_template=_base_system(),
                user_template=(
                    "Given the source material, determine whether the following response is "
                    "a good or bad answer.\n\nSOURCE MATERIAL:\n{source_text}\n\n"
                    "RESPONSE:\n{response}\n\n"
                    "Answer GOOD or BAD with a one-line reason."
                ),
            )
        )
        # Evaluation
        _register(
            TemplateRef(
                name=f"{tf.value}/evaluation",
                version="1",
                task_family=tf.value,
                topology="evaluation",
                system_template=_base_system(),
                user_template=(
                    "Given the source material, generate a clear, self-contained evaluation "
                    "question with a reference answer.\n\nSOURCE MATERIAL:\n{source_text}\n\n"
                    "Return the question and the reference answer."
                ),
            )
        )


_build_registry()


def get_template(task_family: str, topology: str) -> TemplateRef:
    key = (task_family, topology)
    if key not in _REGISTRY:
        # fall back to the generic family if family-specific absent
        key = ("factual_explanation", topology)
    ref = _REGISTRY.get(key)
    if ref is None:
        raise KeyError(f"no template for {task_family}/{topology}")
    return ref


def list_templates() -> list[TemplateRef]:
    return list(_REGISTRY.values())


def template_version(task_family: str, topology: str) -> str:
    return get_template(task_family, topology).version


def render(template: TemplateRef, *, slots: dict[str, Any]) -> tuple[str, str]:
    """Render (system, user) from named slots. Missing slots render empty."""
    system = template.system_template
    user = template.user_template
    safe = {k: (v or "") for k, v in slots.items()}
    try:
        user = user.format(**safe)
        system = system.format(**safe)
    except KeyError as exc:
        # an unknown slot could hide template syntax; render empty for missing
        raise ValueError(f"unknown template slot {exc}") from exc
    return system, user
