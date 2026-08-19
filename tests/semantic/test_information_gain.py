"""Regression test: information gain / non-triviality (defect 4.3)."""

import pytest


@pytest.mark.skip(reason="Information gain validator not yet implemented")
class TestInformationGain:
    """Low-information answers must be rejected."""

    async def test_heading_echo_rejected(self):
        """Heading "MLOps Lifecycle" echoed as answer must be rejected."""
        pytest.fail("Information gain validator not yet implemented")

    async def test_prompt_echo_rejected(self):
        """Answer that merely echoes the prompt must be rejected."""
        pytest.fail("Information gain validator not yet implemented")

    async def test_circular_answer_rejected(self):
        """Circular reasoning must be rejected."""
        pytest.fail("Information gain validator not yet implemented")

    async def test_substantive_answer_accepted(self):
        """A real explanation must be accepted."""
        pytest.fail("Information gain validator not yet implemented")
