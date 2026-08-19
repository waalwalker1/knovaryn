"""Regression tests: REST API consumes all fields."""

import pytest


@pytest.mark.skip(reason="REST endpoint not yet implemented")
class TestAllFieldsConsumed:
    """Every REST request field must be consumed."""

    async def test_all_fields_persisted(self):
        pytest.fail("REST endpoint not yet implemented")
