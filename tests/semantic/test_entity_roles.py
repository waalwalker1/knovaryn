"""Regression test: entity-role reversal detection (defect 4.1).

Given evidence "Bob approved Alice", the answer "Alice approved Bob"
must be rejected with subject_object_reversal.
"""

import pytest


@pytest.mark.skip(reason="Semantic verifier not yet implemented")
class TestEntityRoles:
    """Entity-role reversal detection. See test_causal_direction.py for helpers."""

    async def test_subject_object_reversal_rejected(self):
        pytest.fail("Semantic verifier not yet implemented")
