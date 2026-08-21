"""Package contents (defect 4.13 family): built distributions are clean.

v0.1's sdist shipped the private build-process logs (BUILD_LEDGER.md,
DECISION_LOG.md, SPEC_INDEX.md, VALIDATION_LOG.md) because they sat TRACKED at
the repo root and setuptools' default sdist picked them up. Corrected
contract: build a REAL wheel + sdist from this tree and prove neither carries
a forbidden pattern nor a private process file. This is the functional twin of
the workflow-level scan in ``scripts/public_surface_audit.py``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.public_surface_audit import REPO_ROOT, scan_sdist, scan_wheel


def _uv_cmd() -> list[str]:
    """Locate uv: prefer the binary, fall back to the module entrypoint."""
    uv = shutil.which("uv")
    if uv:
        return [uv]
    return [sys.executable, "-m", "uv"]


pytestmark = pytest.mark.release

PRIVATE_FILES = [
    "BUILD_LEDGER.md",
    "DECISION_LOG.md",
    "SPEC_INDEX.md",
    "VALIDATION_LOG.md",
]


@pytest.fixture(scope="class")
def dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the real wheel + sdist once for the class."""
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(
        [*_uv_cmd(), "build", "--out-dir", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=600,
    )
    return out


class TestPackageContents:
    """The package excludes private build material."""

    def test_wheel_and_sdist_build(self, dist):
        wheels = sorted(dist.glob("*.whl"))
        sdists = sorted(dist.glob("*.tar.gz"))
        assert wheels, f"no wheel built in {dist}"
        assert sdists, f"no sdist built in {dist}"

    def test_no_private_ledger_in_wheel(self, dist):
        for wheel in sorted(dist.glob("*.whl")):
            findings = scan_wheel(str(wheel))
            assert not findings, f"{wheel.name}: {findings}"
            import zipfile

            with zipfile.ZipFile(wheel) as zf:
                names = zf.namelist()
            for name in PRIVATE_FILES:
                assert not any(n.endswith(name) for n in names), (
                    f"private process file {name} inside {wheel.name}"
                )

    def test_no_private_ledger_in_sdist(self, dist):
        for sdist in sorted(dist.glob("*.tar.gz")):
            findings = scan_sdist(str(sdist))
            assert not findings, f"{sdist.name}: {findings}"
            import tarfile

            with tarfile.open(sdist) as tf:
                names = tf.getnames()
            for name in PRIVATE_FILES:
                assert not any(n.endswith(name) for n in names), (
                    f"private process file {name} inside {sdist.name}"
                )

    def test_no_dot_directories_in_archives(self, dist):
        """No archive member may live inside a dot-directory.

        Name-free invariant: hatchling's VCS filter honors .gitignore but not
        local-only excludes (.git/info/exclude), so working-tree dot-dirs
        would otherwise ride into the sdist unchecked by any name-based rule.
        """
        import tarfile
        import zipfile
        from pathlib import PurePosixPath

        def _in_dot_dir(name: str) -> bool:
            parts = PurePosixPath(name).parts
            return any(p.startswith(".") for p in parts[:-1])

        for wheel in sorted(dist.glob("*.whl")):
            with zipfile.ZipFile(wheel) as zf:
                bad = [n for n in zf.namelist() if _in_dot_dir(n)]
            assert not bad, f"{wheel.name} ships dot-directory members: {bad[:5]}"
        for sdist in sorted(dist.glob("*.tar.gz")):
            with tarfile.open(sdist) as tf:
                bad = [m.name for m in tf.getmembers() if _in_dot_dir(m.name)]
            assert not bad, f"{sdist.name} ships dot-directory members: {bad[:5]}"

    def test_sdist_gitignore_is_only_dot_member_and_is_clean(self, dist):
        """Hatchling force-includes the VCS exclusion file into every sdist
        (exported trees must rebuild with identical ignore semantics); it is
        the one permitted dot-member and its content passes the same scan."""
        import tarfile
        from pathlib import PurePosixPath

        from scripts.public_surface_audit import GENERIC_FORBIDDEN_PATTERNS

        for sdist in sorted(dist.glob("*.tar.gz")):
            prefix = sdist.name.removesuffix(".tar.gz")
            with tarfile.open(sdist) as tf:
                dots = [
                    m.name for m in tf.getmembers() if PurePosixPath(m.name).name.startswith(".")
                ]
                assert dots == [f"{prefix}/.gitignore"], (
                    f"unexpected dot-members in {sdist.name}: {dots}"
                )
                member = next(m for m in tf.getmembers() if m.name.endswith("/.gitignore"))
                text = tf.extractfile(member).read().decode("utf-8")
            hits = [p.pattern for p in GENERIC_FORBIDDEN_PATTERNS if p.search(text)]
            assert not hits, f".gitignore leaks forbidden patterns: {hits}"
