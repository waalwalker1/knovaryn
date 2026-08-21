"""Release assets + attestation (defect 4.13 family): the release carries proof.

v0.1 published a bare wheel/sdist to PyPI with no detached checksums, no SBOM,
and no provenance attached anywhere a consumer could find them. Corrected
contract, enforced against the REAL publish pipeline (``publish.yml``) plus a
functional build-and-verify round trip:

* the ``build`` job uploads the dist artifact;
* the ``release-assets`` job generates SHA256SUMS (and verifies them), builds
  a CycloneDX SBOM, and attaches both to the GitHub Release;
* the ``publish`` job uses PyPI OIDC trusted publishing (``id-token: write``),
  which is where PyPI's provenance attestations for the artifacts come from;
* ``security.yml`` keeps a scheduled SBOM job for the source tree.

The functional test mirrors the checksum step locally: build the package,
emit a SHA256SUMS file in the exact format the workflow writes, then verify it
strictly — proving the format the release ships is machine-checkable.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.release


@pytest.fixture(scope="module")
def publish() -> dict:
    text = (REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


@pytest.fixture(scope="module")
def security() -> dict:
    text = (REPO_ROOT / ".github" / "workflows" / "security.yml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def _steps(job: dict) -> list[dict]:
    return job.get("steps", [])


def _step_run_text(job: dict) -> str:
    """Concatenated run: blocks of a job — the thing grep-equivalents match."""
    return "\n".join(str(s.get("run", "")) for s in _steps(job))


def _job(publish: dict, needs: str) -> dict:
    jobs = publish["jobs"]
    assert needs in jobs, f"publish.yml has no {needs!r} job"
    return jobs[needs]


class TestPublishWorkflowAssets:
    """publish.yml attaches checksums + SBOM to the GitHub Release."""

    def test_workflow_parses(self, publish):
        assert publish["name"]
        assert "jobs" in publish

    def test_build_uploads_dist_artifact(self, publish):
        build = _job(publish, "build")
        uploads = [s for s in _steps(build) if "upload-artifact" in str(s.get("uses", ""))]
        assert uploads, "build job never uploads the dist artifact"
        paths = [str(s.get("with", {}).get("path", "")) for s in uploads]
        assert any("dist" in p for p in paths), f"dist not uploaded: {paths}"

    def test_checksums_generated_and_verified(self, publish):
        assets = _job(publish, "release-assets")
        run = _step_run_text(assets)
        assert "sha256sum" in run, "no sha256sum generation step"
        assert "--check" in run and "--strict" in run, (
            "SHA256SUMS is written but never verified in-pipeline"
        )

    def test_sbom_generated(self, publish):
        assets = _job(publish, "release-assets")
        run = _step_run_text(assets)
        assert "cyclonedx" in run, "no CycloneDX SBOM generation step"

    def test_assets_attached_to_github_release(self, publish):
        assets = _job(publish, "release-assets")
        run = _step_run_text(assets)
        assert "gh release upload" in run, "checksums/SBOM never attached to release"
        assert "SHA256SUMS" in run and "sbom.cdx.json" in run

    def test_release_assets_gated_on_build_and_ci(self, publish):
        assets = _job(publish, "release-assets")
        needs = assets.get("needs", [])
        assert "build" in needs and "ci-gate" in needs, (
            f"release-assets must depend on build + ci-gate, got {needs}"
        )

    def test_publish_uses_oidc_trusted_publishing(self, publish):
        pub = _job(publish, "publish")
        perms = pub.get("permissions", {})
        assert perms.get("id-token") == "write", (
            "publish job lacks id-token:write (OIDC attestation source)"
        )
        uses = [str(s.get("uses", "")) for s in _steps(pub)]
        assert any("pypa/gh-action-pypi-publish" in u for u in uses), (
            f"publish does not use pypa/gh-action-pypi-publish: {uses}"
        )
        run = _step_run_text(pub)
        assert "PYPI_API_TOKEN" not in run and "password" not in run.lower(), (
            "publish must not fall back to a stored token"
        )


class TestSecurityWorkflowSbom:
    """security.yml keeps a scheduled SBOM job for the source tree."""

    def test_sbom_job_exists(self, security):
        assert "sbom" in security["jobs"], "security.yml lost its sbom job"
        run = _step_run_text(security["jobs"]["sbom"])
        assert "cyclonedx" in run

    def test_sbom_uploaded_as_artifact(self, security):
        steps = _steps(security["jobs"]["sbom"])
        assert any("upload-artifact" in str(s.get("uses", "")) for s in steps)


class TestChecksumRoundTrip:
    """The SHA256SUMS format the workflow ships is verifiable end to end."""

    def test_build_then_verify_sha256sums(self, tmp_path: Path):
        import shutil
        import subprocess
        import sys

        uv = shutil.which("uv")
        cmd = [uv] if uv else [sys.executable, "-m", "uv"]
        out = tmp_path / "dist"
        out.mkdir()
        subprocess.run(
            [*cmd, "build", "--out-dir", str(out)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=600,
        )
        artifacts = sorted(out.glob("*.whl")) + sorted(out.glob("*.tar.gz"))
        assert artifacts, f"uv build produced no artifacts in {out}"

        # Emit SHA256SUMS exactly as the workflow does: "<digest>  <name>".
        lines = []
        for artifact in artifacts:
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            lines.append(f"{digest}  {artifact.name}")
        sums = out / "SHA256SUMS"
        sums.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Verify strictly: every listed file present, digest matching, and no
        # unlisted artifact hiding in the directory.
        listed: dict[str, str] = {}
        for line in sums.read_text(encoding="utf-8").splitlines():
            digest, name = line.split(maxsplit=1)
            listed[name.strip().lstrip("*")] = digest
        assert set(listed) == {a.name for a in artifacts}, "SHA256SUMS coverage gap"
        for name, digest in listed.items():
            actual = hashlib.sha256((out / name).read_bytes()).hexdigest()
            assert actual == digest, f"{name}: checksum mismatch"
