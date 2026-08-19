"""Regression tests: invalid scopes fail (defect 4.10)."""

import pytest


@pytest.mark.skip(reason="Security module not yet implemented")
class TestInvalidScopesFail:
    """Invalid scope names must raise startup/configuration error."""

    async def test_invalid_scope_name_fails(self):
        pytest.fail("Security module not yet implemented")

    async def test_empty_scope_list_means_no_privileges(self):
        pytest.fail("Security module not yet implemented")
