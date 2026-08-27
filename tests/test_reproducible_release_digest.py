"""Regression tests: reproducible-mode IDs and byte-identical release bundles.

Contract §6.3 requires benchmark repetitions to satisfy
``H(R1) = H(R2) = H(R3)`` — the release-bundle digest must depend on inputs
only. The v0.1.0 report already showed bundle sizes drifting between runs;
root cause: ``IdGenerator`` minted wall-clock UUIDv7s, so project/example
handles (and everything derived from them) changed every run.

Fix: opt-in seeded mode on ``IdGenerator`` (HMAC-SHA256 over a counter).
Production default is unchanged (unguessable UUIDv7 handles), and security
tokens stay ``secrets``-based even in seeded mode.
"""

from __future__ import annotations

import re

import pytest

from knovaryn.domain.ids import IdGenerator

pytestmark = pytest.mark.unit


class TestSeededIdGenerator:
    def test_same_seed_yields_identical_handle_sequences(self):
        a, b = IdGenerator(seed="s"), IdGenerator(seed="s")
        seq_a = [a.new_handle("src") for _ in range(20)]
        seq_b = [b.new_handle("src") for _ in range(20)]
        assert seq_a == seq_b

    def test_different_seed_yields_different_handles(self):
        a, b = IdGenerator(seed="s1"), IdGenerator(seed="s2")
        assert a.new() != b.new()

    def test_seeded_handles_are_valid_uuid_strings(self):
        g = IdGenerator(seed="s")
        v = g.new()
        assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", v), (
            f"seeded id is not a canonical UUID string: {v!r}"
        )

    def test_default_generator_is_not_deterministic(self):
        """The production default must remain wall-clock/random — two fresh
        generators must not emit identical sequences."""
        a, b = IdGenerator(), IdGenerator()
        seq_a = [a.new() for _ in range(8)]
        seq_b = [b.new() for _ in range(8)]
        assert seq_a != seq_b

    def test_tokens_stay_secret_even_in_seeded_mode(self):
        """new_token is security material: never reproducible, even with a seed."""
        a, b = IdGenerator(seed="s"), IdGenerator(seed="s")
        tokens_a = {a.new_token() for _ in range(16)}
        tokens_b = {b.new_token() for _ in range(16)}
        assert len(tokens_a) == 16 and not (tokens_a & tokens_b)


async def _run_pipeline_bundle(seed: str):
    from knovaryn.application.service import ProjectService
    from knovaryn.domain.ids import IdGenerator as G
    from knovaryn.domain.schemas import DatasetPlan, Project, SourceDocument, SourceKind

    ids = G(seed=seed)
    project = Project(
        id=ids.new_handle("proj"),
        slug="repro",
        display_name="Repro",
        owner_principal="bench",
    )
    plan = DatasetPlan(
        task_family_proportions={"factual_explanation": 0.5, "procedure": 0.3, "comparison": 0.2},
    )
    body = (
        b"# Handbook\n\nA widget converts pressure into rotation.\n"
        b"## Maintenance\n\nInspect the valve monthly.\n"
        b"## Assembly\n\nTorque the housing to 12 Nm.\n"
    )
    source = SourceDocument(
        id=ids.new_handle("src"),
        project_id=project.id,
        original_name="handbook.md",
        media_type="text/markdown",
        byte_size=len(body),
        sha256="0" * 64,
        source_kind=SourceKind.local_path,
        group_key="handbook.md",
    )
    svc = ProjectService(ids=G(seed=seed))
    result = await svc.run_pipeline(
        project=project, sources=[source], raw_contents=[body], plan=plan
    )
    return result


class TestReleaseBundleDigestEquality:
    async def test_two_runs_same_seed_produce_identical_bundle_digests(self):
        r1 = await _run_pipeline_bundle("regression-seed")
        r2 = await _run_pipeline_bundle("regression-seed")
        assert r1.release_bundle_bytes, "pipeline must produce a release bundle"
        import hashlib

        h1 = hashlib.sha256(r1.release_bundle_bytes).hexdigest()
        h2 = hashlib.sha256(r2.release_bundle_bytes).hexdigest()
        assert h1 == h2, (
            "release-bundle digest drifted between identical seeded runs — "
            "wall-clock state leaked into the artifact"
        )
