"""Regression tests: release assets and attestation."""

import pytest


@pytest.mark.skip(reason="Release governance not yet implemented")
class TestAssetsAndAttestation:
    """Release must include wheel, sdist, checksums, SBOM, attestation."""

    async def test_wheel_attached(self):
        pytest.fail("Release governance not yet implemented")

    async def test_sdist_attached(self):
        pytest.fail("Release governance not yet implemented")

    async def test_checksum_files_attached(self):
        pytest.fail("Release governance not yet implemented")

    async def test_sbom_attached(self):
        pytest.fail("Release governance not yet implemented")

    async def test_provenance_attestation_attached(self):
        pytest.fail("Release governance not yet implemented")
