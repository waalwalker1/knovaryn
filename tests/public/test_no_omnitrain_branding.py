"""Regression tests: no OmniTrain branding."""

import pytest


@pytest.mark.skip(reason="Branding check not yet integrated")
class TestNoOmnitrainBranding:
    """No OmniTrain branding in public surfaces."""

    async def test_no_omnitrain_in_docs(self):
        pytest.fail("Branding check not yet integrated")

    async def test_no_omnitrain_in_package(self):
        pytest.fail("Branding check not yet integrated")
