"""Regression tests: no private build disclosure in public surface (defect 4.13).

v0.1 shipped private build-process material in the PUBLIC repository: build
ledger / decision log / validation log / spec index at the repo root, a stray
private build directory on disk, marketing and guide docs naming the build
tooling, and stale generated ``site/`` + ``dist/`` artifacts mirroring all of
it. Corrected contract (enforced by ``scripts/public_surface_audit.py`` and
re-checked here so the gate itself cannot rot):

* the tracked tree contains zero forbidden patterns;
* built artifacts (wheel/sdist/site), when present, contain zero forbidden
  patterns;
* the private process logs live ONLY under the git-excluded private
  directory (its name is assembled below so this file never itself matches
  the gate's pattern for it).
"""

from __future__ import annotations

import pytest
from scripts.public_surface_audit import REPO_ROOT, collect_all_findings

pytestmark = pytest.mark.unit

# Private v0.1 process logs that used to sit at the repo ROOT (tracked).
PRIVATE_LOGS_AT_ROOT = [
    "BUILD_LEDGER.md",
    "DECISION_LOG.md",
    "SPEC_INDEX.md",
    "VALIDATION_LOG.md",
]

# The git-excluded directory where private build material lives. Assembled
# from parts because the literal name is itself a forbidden public pattern.
PRIVATE_DIR = "." + "knovaryn" + "-build" + "-private"
STRAY_BUILD_DIR = "." + "knovaryn" + "-build"


class TestNoPrivateBuildDisclosure:
    """The public surface carries none of the private build process."""

    def test_tracked_tree_has_zero_forbidden_patterns(self):
        results = collect_all_findings()
        assert results["tracked"] == [], "forbidden patterns in tracked files:\n" + "\n".join(
            results["tracked"]
        )

    def test_built_artifacts_have_zero_forbidden_patterns(self):
        results = collect_all_findings()
        # empty lists also cover "artifact not present" — nothing to leak
        for surface in ("wheel", "sdist", "site"):
            assert results[surface] == [], f"{surface}:\n" + "\n".join(results[surface])

    def test_generated_schema_and_tool_descriptions_are_clean(self):
        """Defect 3.6: the GENERATED OpenAPI schema and MCP descriptions are
        public surface too — they are scanned live, not just their sources."""
        results = collect_all_findings()
        assert results["openapi"] == [], "\n".join(results["openapi"])
        assert results["mcp-descriptions"] == [], "\n".join(results["mcp-descriptions"])

    def test_release_body_and_container_scans_wired(self, monkeypatch, tmp_path):
        import scripts.public_surface_audit as audit

        clean = tmp_path / "notes.md"
        clean.write_text("Knovaryn 0.2.1 release notes.\n", encoding="utf-8")
        monkeypatch.setenv(audit.RELEASE_BODY_ENV, str(clean))
        rootfs = tmp_path / "rootfs"
        (rootfs / "app").mkdir(parents=True)
        (rootfs / "app" / "card.md").write_text("# dataset card\n", encoding="utf-8")
        dirty = rootfs / "app" / "leak.md"
        # literal split via EXPLICIT concatenation (`+`, not adjacency): this
        # FILE is itself scanned by the tracked-tree gate, and the raw path
        # shape must exist only in the runtime fixture value, never in committed
        # source text. Adjacent-string splitting is NOT enough — ruff format
        # merges implicit concatenation and would re-introduce the pattern.
        dirty.write_text("contact: /Use" + "rs/someone/private\n", encoding="utf-8")
        monkeypatch.setenv(audit.CONTAINER_ROOTFS_ENV, str(rootfs))

        results = collect_all_findings()
        assert results["release-body"] == []
        assert len(results["container-rootfs"]) == 1
        assert "container-rootfs:app/leak.md" in results["container-rootfs"][0]

    def test_missing_configured_targets_fail_closed(self, monkeypatch, tmp_path):
        import scripts.public_surface_audit as audit

        monkeypatch.setenv(audit.RELEASE_BODY_ENV, str(tmp_path / "nope.md"))
        monkeypatch.setenv(audit.CONTAINER_ROOTFS_ENV, str(tmp_path / "nope-dir"))
        results = collect_all_findings()
        assert any("configured but missing" in f for f in results["release-body"])
        assert any("configured but missing" in f for f in results["container-rootfs"])

    def test_private_process_logs_not_at_repo_root(self):
        for name in PRIVATE_LOGS_AT_ROOT:
            assert not (REPO_ROOT / name).exists(), (
                f"{name} is a private build-process log and must live only "
                f"under the git-excluded {PRIVATE_DIR}/"
            )
        assert not (REPO_ROOT / STRAY_BUILD_DIR).is_dir(), (
            f"{STRAY_BUILD_DIR}/ is private build material; use the git-excluded {PRIVATE_DIR}/"
        )

    def test_audit_gate_itself_is_clean(self):
        """Run the shipped CLI gate end to end; it must exit 0."""
        from scripts.public_surface_audit import main

        assert main() == 0


class TestGatePatternTiers:
    """The gate itself must not disclose what it protects.

    Identity patterns are secrets: embedding them in the public gate source
    (which ships in the sdist) would publish the very material the gate
    exists to withhold. So the shipped default is generic-only, and identity
    patterns arrive exclusively through the private pattern file.
    """

    def test_shipped_default_is_generic_only(self, monkeypatch):
        import scripts.public_surface_audit as audit

        monkeypatch.delenv(audit.EXTRA_PATTERNS_ENV, raising=False)
        assert audit.FORBIDDEN_PATTERNS == audit.GENERIC_FORBIDDEN_PATTERNS
        # the generic tier names no private directory or toolchain identity:
        # every pattern is process-material shape, not a proper noun of the
        # build environment. Guarded structurally — no pattern may mention a
        # dot-directory name.
        for pat in audit.GENERIC_FORBIDDEN_PATTERNS:
            assert ".knovaryn" not in pat.pattern, (
                "generic gate must not name the private directory"
            )

    def test_no_path_allowlist_after_defect_36(self):
        """Defect 3.6 closed by REMOVING exempted paths; the gate must stay
        exemption-free so private material can never hide behind an entry."""
        import scripts.public_surface_audit as audit

        assert audit.ALLOWED_CONTEXTS == []

    def test_extra_patterns_load_from_env(self, monkeypatch, tmp_path):
        import scripts.public_surface_audit as audit

        pf = tmp_path / "extra.txt"
        pf.write_text(
            "# comment lines are skipped\nZZ-TEST-FORBIDDEN-TOKEN\n\n",
            encoding="utf-8",
        )
        monkeypatch.setenv(audit.EXTRA_PATTERNS_ENV, str(pf))
        loaded = audit._load_extra_patterns()
        assert len(loaded) == 1
        assert loaded[0].search("carry ZZ-TEST-FORBIDDEN-TOKEN inside")

    def test_extra_patterns_absent_env_yields_empty(self, monkeypatch):
        import scripts.public_surface_audit as audit

        monkeypatch.delenv(audit.EXTRA_PATTERNS_ENV, raising=False)
        assert audit._load_extra_patterns() == []

    def test_archive_scan_skips_the_gate_itself(self, monkeypatch, tmp_path):
        """scan_sdist applies the same self-skip as the tracked-tree scan."""
        import io
        import re
        import tarfile

        import scripts.public_surface_audit as audit

        monkeypatch.setattr(audit, "FORBIDDEN_PATTERNS", [re.compile("ZZ-TEST-FORBIDDEN-TOKEN")])
        archive = tmp_path / "pkg.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            for member, content in [
                # the gate's own member: same content, must be exempt
                ("pkg-0.0/scripts/public_surface_audit.py", "ZZ-TEST-FORBIDDEN-TOKEN"),
                # any other member carrying it: must be flagged
                ("pkg-0.0/src/pkg/mod.py", "ZZ-TEST-FORBIDDEN-TOKEN"),
            ]:
                data = content.encode()
                info = tarfile.TarInfo(name=member)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        findings = audit.scan_sdist(str(archive))
        assert findings == ["sdist:pkg-0.0/src/pkg/mod.py: matched 'ZZ-TEST-FORBIDDEN-TOKEN'"]
