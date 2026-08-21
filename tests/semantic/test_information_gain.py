"""Regression test: information gain / non-triviality (defect 4.3)."""

from knovaryn.pipeline.quality.information_gain import assess_information_gain


class TestInformationGain:
    """Low-information answers must be rejected."""

    def test_heading_echo_rejected(self):
        """Heading "MLOps Lifecycle" echoed as answer must be rejected."""
        result = assess_information_gain(
            answer="MLOps Lifecycle",
            prompt="What is the MLOps lifecycle?",
            heading="MLOps Lifecycle",
            task_type="factual_explanation",
        )
        assert result.score < 0.3, f"Expected low score for heading echo, got {result.score}"
        assert "heading_echo" in " ".join(result.reason_codes), result.reason_codes

    def test_prompt_echo_rejected(self):
        """Answer that merely echoes the prompt must be rejected."""
        result = assess_information_gain(
            answer="What is the MLOps lifecycle? The MLOps lifecycle is.",
            prompt="What is the MLOps lifecycle?",
            task_type="factual_explanation",
        )
        assert result.score < 0.3, f"Expected low score for prompt echo, got {result.score}"
        assert "prompt_echo" in " ".join(result.reason_codes), result.reason_codes

    def test_circular_answer_rejected(self):
        """Circular reasoning must be rejected."""
        result = assess_information_gain(
            answer=(
                "The answer is what the question asks about. "
                "What the question asks about is the answer."
            ),
            prompt="What is the meaning of life?",
            task_type="factual_explanation",
        )
        # Circularity is detected via metalinguistic/self-referential dominance
        assert result.score < 0.3, f"Expected low score for circular answer, got {result.score}"
        assert any(
            "circular" in c or "repetition" in c or "unique" in c for c in result.reason_codes
        ), result.reason_codes

    def test_substantive_answer_accepted(self):
        """A real explanation must be accepted."""
        result = assess_information_gain(
            answer="The MLOps lifecycle covers data collection, model training, deployment, "
            "monitoring, and iterative improvement. It ensures reliable ML pipelines "
            "in production.",
            prompt="What is the MLOps lifecycle?",
            heading="MLOps Lifecycle",
            task_type="factual_explanation",
        )
        assert result.score >= 0.5, (
            f"Expected high score for substantive answer, got {result.score}"
        )
        assert len(result.reason_codes) == 0, f"Unexpected reason codes: {result.reason_codes}"

    def test_boilerplate_only_rejected(self):
        """Boilerplate-only answer must be rejected."""
        result = assess_information_gain(
            answer=(
                "According to the provided material, "
                "the information states the following key points."
            ),
            prompt="What is the answer?",
            task_type="factual_explanation",
        )
        assert result.score < 0.3, f"Expected low score for boilerplate, got {result.score}"
        assert "boilerplate_only" in result.reason_codes, result.reason_codes

    def test_disclaimer_only_rejected(self):
        """Disclaimer-only response must be rejected."""
        result = assess_information_gain(
            answer=(
                "I am sorry, but I cannot answer this question based on the provided information."
            ),
            prompt="What is the answer?",
            task_type="refusal",
        )
        assert result.score < 0.3, f"Expected low score for disclaimer, got {result.score}"
        assert "disclaimer_only" in result.reason_codes, result.reason_codes

    def test_comparison_missing_dimension(self):
        """Comparison must include comparison markers."""
        result = assess_information_gain(
            answer=(
                "The first system has high accuracy and the second system has high accuracy too."
            ),
            prompt="Compare system A and system B.",
            task_type="comparison",
        )
        assert result.score < 0.5, f"Expected low score for missing comparison, got {result.score}"
        assert "missing_comparison_dimension" in result.reason_codes, result.reason_codes
