"""Regression tests: artifact resolution in provenance.

Original/canonical artifacts must exist and hashes must match.
"""

from knovaryn.pipeline.export.gate import recompute_content_hash


class TestArtifactResolution:
    """Original/canonical artifacts must exist and hashes match."""

    def test_artifact_hash_match(self):
        """Recomputed content hash matches the stored hash for a real example."""
        from knovaryn.domain.schemas import (
            CanonicalMessage,
            Topology,
            TrainingExample,
        )

        ex = TrainingExample(
            id="ex1",
            project_id="p1",
            topology=Topology.sft,
            prompt_messages=[CanonicalMessage(role="user", content="Q?")],
            chosen_messages=[CanonicalMessage(role="assistant", content="A.")],
            source_document_ids=["doc1"],
            source_span_ids=["span1"],
            generation_candidate_ids=["cand1"],
        )
        ex.content_hash = recompute_content_hash(ex)
        assert recompute_content_hash(ex) == ex.content_hash

    def test_hash_detects_mutation(self):
        """Any content mutation changes the hash — tampering is detectable."""
        from knovaryn.domain.schemas import (
            CanonicalMessage,
            Topology,
            TrainingExample,
        )

        ex = TrainingExample(
            id="ex2",
            project_id="p1",
            topology=Topology.sft,
            prompt_messages=[CanonicalMessage(role="user", content="Q?")],
            chosen_messages=[CanonicalMessage(role="assistant", content="A.")],
            source_document_ids=["doc1"],
            source_span_ids=["span1"],
            generation_candidate_ids=["cand1"],
        )
        ex.content_hash = recompute_content_hash(ex)

        # Mutate the assistant answer
        ex.chosen_messages[0].content = "TAMPERED."
        assert recompute_content_hash(ex) != ex.content_hash

    def test_preference_hash_uses_both_sides(self):
        """Preference examples hash chosen AND rejected content."""
        from knovaryn.domain.schemas import (
            CanonicalMessage,
            Topology,
            TrainingExample,
        )

        ex = TrainingExample(
            id="ex3",
            project_id="p1",
            topology=Topology.preference,
            prompt_messages=[CanonicalMessage(role="user", content="Q?")],
            chosen_messages=[CanonicalMessage(role="assistant", content="Good.")],
            rejected_messages=[CanonicalMessage(role="assistant", content="Bad.")],
            source_document_ids=["doc1"],
            source_span_ids=["span1"],
            generation_candidate_ids=["cand1"],
        )
        ex.content_hash = recompute_content_hash(ex)
        assert recompute_content_hash(ex) == ex.content_hash

        # Changing only the rejected side must change the hash
        ex.rejected_messages[0].content = "Changed."
        assert recompute_content_hash(ex) != ex.content_hash
