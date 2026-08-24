"""Semantic validation profiles (defect 3.8, v0.2.1).

Two explicit, documented profiles — nothing in between:

``offline-fast``
    Deterministic semantic checks only. No network, no model calls.
    Suitable for demos, tests, and initial curation. LIMITS: catches
    contradiction classes only (entity-role/causal reversal, negation,
    number/date/unit mismatch, unsupported entities); it cannot prove
    entailment for paraphrases or multi-hop claims and never upgrades a
    claim past ``unverified`` on its own.

``certified-semantic``
    Deterministic checks first; a typed, cited-evidence-only NLI/judge call
    second (via ``ModelGateway.judge``: temperature 0, fingerprinted,
    cached, budget-accounted, ledgered). Deterministic contradictions can
    never be overridden by the judge; an unavailable judge yields
    ``unverified``, never ``verified``; judge identity + prompt template +
    schema hash are recorded in quality lineage.

The word "certified" refers to this *profile's* fail-closed contract — the
published adversarial benchmark evidence lives in
``tests/quality/test_semantic_benchmark.py`` and must be regenerated with
each policy version before any public certification claim is made.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .semantic import (
    CompositeSemanticVerifier,
    DeterministicSemanticVerifier,
    ModelSemanticVerifier,
    SemanticVerifier,
    VerifierConfig,
)

PROFILE_OFFLINE_FAST = "offline-fast"
PROFILE_CERTIFIED_SEMANTIC = "certified-semantic"
SEMANTIC_PROFILES = (PROFILE_OFFLINE_FAST, PROFILE_CERTIFIED_SEMANTIC)

# Preference-judge profiles (defect 3.9). "heuristic" is deterministic-only;
# "certified-pairwise" adds CertifiedPairwiseJudge behind an explicit opt-in.
PROFILE_HEURISTIC = "heuristic"
PROFILE_CERTIFIED_PAIRWISE = "certified-pairwise"


@dataclass(frozen=True)
class SemanticProfileSpec:
    """Metadata recorded alongside quality lineage when a profile runs."""

    name: str
    uses_model_judge: bool
    network_required: bool
    limits: str


SPECS: dict[str, SemanticProfileSpec] = {
    PROFILE_OFFLINE_FAST: SemanticProfileSpec(
        name=PROFILE_OFFLINE_FAST,
        uses_model_judge=False,
        network_required=False,
        limits=(
            "deterministic contradiction checks only; no entailment for "
            "paraphrases or multi-hop claims; claims without a deterministic "
            "contradiction remain unverified rather than certified"
        ),
    ),
    PROFILE_CERTIFIED_SEMANTIC: SemanticProfileSpec(
        name=PROFILE_CERTIFIED_SEMANTIC,
        uses_model_judge=True,
        network_required=True,
        limits=(
            "judge verdicts are evidence-scoped to cited spans; unavailable "
            "or invalid judge output yields unverified (fail-closed); "
            "deterministic contradictions are final"
        ),
    ),
}


def spec_for(profile: str) -> SemanticProfileSpec:
    try:
        return SPECS[profile]
    except KeyError:
        raise ValueError(
            f"unknown semantic profile {profile!r}; expected one of "
            f"{sorted(SPECS)}"
        ) from None


def build_semantic_verifier(
    profile: str,
    *,
    gateway: Any | None = None,
) -> SemanticVerifier:
    """Construct the verifier stack for a named profile.

    ``certified-semantic`` requires a gateway exposing ``async judge(...)``;
    constructing it without one is an error at wiring time, not a silent
    fallback to offline behavior.
    """
    spec = spec_for(profile)
    if not spec.uses_model_judge:
        return CompositeSemanticVerifier(
            deterministic_verifier=DeterministicSemanticVerifier(),
            model_verifier=None,
            config=VerifierConfig(offline_mode=True),
        )
    if gateway is None:
        raise ValueError(
            f"profile '{PROFILE_CERTIFIED_SEMANTIC}' requires a model gateway "
            "with `judge()` support; pass one explicitly or use "
            f"'{PROFILE_OFFLINE_FAST}'"
        )
    return CompositeSemanticVerifier(
        deterministic_verifier=DeterministicSemanticVerifier(),
        model_verifier=ModelSemanticVerifier(model_gateway=gateway),
        config=VerifierConfig(
            require_deterministic_checks=True,
            offline_mode=False,
        ),
    )
