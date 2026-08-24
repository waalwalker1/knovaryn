#!/usr/bin/env python3
"""public_surface_audit.py — fail when public surface contains private-build material.

This is a CI/SECURITY gate. It scans tracked files, built packages, and the
generated documentation site for patterns that should never appear in the
public repository or published artifacts.
"""

import asyncio
import json
import os
import re
import sys
import tarfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Forbidden patterns — match full-text in .md, .py, .html, .toml, .yaml, .yml,
# .json, .cfg, .ini files. Two tiers, on purpose:
#
# * GENERIC patterns ship in this public file. They name build-process
#   *material* (prompt/ledger/audit artifacts, machine paths) and disclose
#   nothing by being listed — the same way a linter's dictionary must contain
#   the misspellings it flags.
#
# * IDENTITY patterns are themselves secrets: writing them into this public
#   file would disclose exactly what this gate exists to protect. They live
#   in a git-excluded pattern file and load only when
#   KNOVARYN_EXTRA_FORBIDDEN_PATTERNS points at it (one regex per line,
#   '#' comments). CI and public checkouts run the generic gate; the private
#   build environment layers the identity patterns on top
#   (run_private_surface_gate.sh).
#
# Keep every pattern a build-process identifier, not a valid runtime product
# term (a provider/model string is legitimate runtime configuration; the same
# string identifying the BUILD toolchain is not).
# ---------------------------------------------------------------------------
GENERIC_FORBIDDEN_PATTERNS: list[re.Pattern] = [
    # -- private process material -----------------------------------------
    re.compile(r"one-shot build prompt", re.IGNORECASE),
    re.compile(r"private execution contract", re.IGNORECASE),
    re.compile(r"private (build|audit|repair) (prompt|contract|session|log)", re.IGNORECASE),
    re.compile(r"coding[- ]agent (process|session|transcript)", re.IGNORECASE),
    re.compile(r"maintainer-only", re.IGNORECASE),
    re.compile(r"Soviet judge", re.IGNORECASE),
    re.compile(r"internal 10/10 audit", re.IGNORECASE),
    # -- local filesystem / machine paths ---------------------------------
    re.compile(r"/private/tmp/"),
    re.compile(r"/Users/\w+/"),
    re.compile(r"C:\\Users\\\w+\\"),
    re.compile(r"OneDrive"),
    # -- obsolete implementation snapshots (defect 3.6): counts frozen in
    #    prose go stale immediately; CI badges are the sanctioned alternative
    re.compile(r"\b17 tools\b"),
    re.compile(r"\b(233|48)\s+tests\b"),
]

EXTRA_PATTERNS_ENV = "KNOVARYN_EXTRA_FORBIDDEN_PATTERNS"
# Optional scan targets beyond the tree/packages/site (defect 3.6 requires
# the audit to reach the generated OpenAPI schema, MCP tool descriptions,
# the release body, and an extracted container filesystem when available).
RELEASE_BODY_ENV = "KNOVARYN_RELEASE_BODY"
CONTAINER_ROOTFS_ENV = "KNOVARYN_CONTAINER_ROOTFS"


def _load_extra_patterns(env_var: str = EXTRA_PATTERNS_ENV) -> list[re.Pattern]:
    """Load private (identity) forbidden patterns, if configured.

    Absent the env var — the case in CI and any public checkout — this
    returns [] and the generic gate stands alone.
    """
    raw = os.environ.get(env_var, "")
    if not raw:
        return []
    path = Path(raw)
    if not path.is_file():
        return []
    patterns: list[re.Pattern] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(re.compile(line, re.IGNORECASE))
    return patterns


FORBIDDEN_PATTERNS: list[re.Pattern] = GENERIC_FORBIDDEN_PATTERNS + _load_extra_patterns()

# Defect 3.6: nothing is exempt any more. The obsolete build report and the
# marketing/launch drafts were removed from the tree entirely; a path
# allowlist here would only invite new private material to hide behind it.
ALLOWED_CONTEXTS: list[re.Pattern] = []

# Dot-directories are tool state or private material — never public surface —
# so they are excluded generically (this file names no private path).
# .github is tracked, public workflow configuration and stays in scope.
_SCANNED_DOT_DIRS = {".github"}
_JUNK_DIRS = {"__pycache__", "node_modules"}

# The gate ships inside the sdist; its source holds the generic pattern
# definitions (the linter-dictionary rule above), so archive scans skip the
# gate's own member exactly as the tree scan skips the gate's own file.
_SELF_MEMBER_SUFFIX = "/" + str(Path(__file__).resolve().relative_to(REPO_ROOT))

SKIP_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".zip",
    ".gz",
    ".bz2",
    ".xz",
    ".whl",
}


def _should_check_path(path: Path) -> bool:
    """Return True if the file should be scanned for forbidden patterns."""
    if path.resolve() == Path(__file__).resolve():
        return False  # this gate defines the generic patterns; it cannot scan itself
    if path.suffix.lower() in SKIP_EXTENSIONS:
        return False
    if path.name == ".gitignore":
        return True  # dotfile with no suffix; scan it like any text file
    # Dot-directories hold tool state / private material, never public
    # surface; .github is tracked public configuration and stays in scope.
    # Non-dot junk dirs are build/tool output with nothing to say.
    if any(
        (part.startswith(".") and part not in _SCANNED_DOT_DIRS) or part in _JUNK_DIRS
        for part in path.parts[:-1]
    ):
        return False
    # Only check text-like files
    return path.suffix.lower() in {
        ".md",
        ".py",
        ".html",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".cfg",
        ".ini",
        ".txt",
        ".css",
        ".js",
        ".xml",
    }


def _is_allowed(filepath: str) -> bool:
    return any(pat.search(filepath) for pat in ALLOWED_CONTEXTS)


def scan_tracked_files() -> list[str]:
    """Walk the repository source tree (git-tracked-equivalent) for forbidden patterns."""
    findings: list[str] = []
    for root, dirs, files in os.walk(REPO_ROOT):
        # Prune dot-dirs (tool state / private material) and junk dirs; .github
        # stays in scope as tracked public configuration.
        dirs[:] = [
            d
            for d in dirs
            if (d in _SCANNED_DOT_DIRS or not d.startswith(".")) and d not in _JUNK_DIRS
        ]
        for fn in files:
            fpath = Path(root) / fn
            if not _should_check_path(fpath):
                continue
            rel = fpath.relative_to(REPO_ROOT)
            if _is_allowed(str(rel)):
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for pattern in FORBIDDEN_PATTERNS:
                for lineno, line in enumerate(text.splitlines(), 1):
                    if pattern.search(line):
                        findings.append(f"{rel}:{lineno}: matched {pattern.pattern!r}")
                        break  # one finding per pattern per file
    return findings


def scan_wheel(path: str) -> list[str]:
    """Check a .whl (zip) archive for forbidden patterns."""
    findings: list[str] = []
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for name in zf.namelist():
                if name.endswith(_SELF_MEMBER_SUFFIX):
                    continue  # the gate does not scan itself
                if _is_allowed(name):
                    continue
                ext = Path(name).suffix.lower()
                if ext in SKIP_EXTENSIONS or ext not in {
                    ".md",
                    ".py",
                    ".html",
                    ".toml",
                    ".txt",
                    ".cfg",
                    ".ini",
                    ".json",
                }:
                    continue
                try:
                    text = zf.read(name).decode("utf-8")
                except Exception:
                    continue
                for pattern in FORBIDDEN_PATTERNS:
                    if pattern.search(text):
                        findings.append(f"wheel:{name}: matched {pattern.pattern!r}")
    except FileNotFoundError:
        findings.append(f"Wheel not found at {path}")
    return findings


def scan_sdist(path: str) -> list[str]:
    """Check a .tar.gz source distribution for forbidden patterns."""
    findings: list[str] = []
    try:
        with tarfile.open(path, "r:gz") as tf:
            for member in tf.getmembers():
                if member.name.endswith(_SELF_MEMBER_SUFFIX):
                    continue  # the gate does not scan itself
                if _is_allowed(member.name):
                    continue
                ext = Path(member.name).suffix.lower()
                if ext in SKIP_EXTENSIONS or ext not in {
                    ".md",
                    ".py",
                    ".html",
                    ".toml",
                    ".txt",
                    ".cfg",
                    ".ini",
                    ".json",
                }:
                    continue
                if not member.isfile():
                    continue
                try:
                    f = tf.extractfile(member)
                    if f is None:
                        continue
                    text = f.read().decode("utf-8")
                except Exception:
                    continue
                for pattern in FORBIDDEN_PATTERNS:
                    if pattern.search(text):
                        findings.append(f"sdist:{member.name}: matched {pattern.pattern!r}")
    except FileNotFoundError:
        findings.append(f"Sdist not found at {path}")
    return findings


def scan_site_dir(site_path: str) -> list[str]:
    """Check the built documentation site."""
    findings: list[str] = []
    site = Path(site_path)
    if not site.is_dir():
        findings.append(f"Site directory not found at {site_path}")
        return findings
    for root, dirs, files in os.walk(site):
        dirs[:] = [
            d
            for d in dirs
            if (d in _SCANNED_DOT_DIRS or not d.startswith(".")) and d not in _JUNK_DIRS
        ]
        for fn in files:
            fpath = Path(root) / fn
            if not _should_check_path(fpath):
                continue
            rel = fpath.relative_to(site)
            if _is_allowed(str(rel)):
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for pattern in FORBIDDEN_PATTERNS:
                if pattern.search(text):
                    findings.append(f"site:{rel}: matched {pattern.pattern!r}")
    return findings


def _scan_text(text: str, label: str) -> list[str]:
    findings: list[str] = []
    for pattern in FORBIDDEN_PATTERNS:
        if pattern.search(text):
            findings.append(f"{label}: matched {pattern.pattern!r}")
    return findings


def scan_openapi_schema() -> list[str]:
    """Scan the GENERATED OpenAPI schema (defect 3.6), not only its source.

    Silent skip when FastAPI is absent (minimal/offline environments).
    """
    try:
        from knovaryn.interfaces.rest.app import app as rest_app
    except Exception:
        return []
    return _scan_text(json.dumps(rest_app.openapi()), "openapi")


def scan_mcp_descriptions() -> list[str]:
    """Scan every registered MCP tool's name + description (defect 3.6)."""
    try:
        from knovaryn.interfaces.mcp.server import build_server
    except Exception:
        return []

    async def _tools():
        return await build_server().list_tools()

    findings: list[str] = []
    for tool in asyncio.run(_tools()):
        blob = f"{tool.name}\n{tool.description or ''}"
        findings.extend(_scan_text(blob, f"mcp-tool:{tool.name}"))
    return findings


def scan_release_body(path: str | None) -> list[str]:
    """Scan a release body / notes file when one is configured."""
    if not path:
        return []
    p = Path(path)
    if not p.is_file():
        return [f"release-body:{path}: configured but missing"]
    return _scan_text(p.read_text(encoding="utf-8", errors="replace"), "release-body")


def scan_container_rootfs(root: str | None) -> list[str]:
    """Scan an extracted container filesystem when one is configured.

    Point ``KNOVARYN_CONTAINER_ROOTFS`` at a ``docker export`` directory tree;
    every text-like file inside is scanned exactly like tracked files.
    """
    if not root:
        return []
    base = Path(root)
    if not base.is_dir():
        return [f"container-rootfs:{root}: configured but missing"]
    findings: list[str] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file() or not _should_check_path(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        findings.extend(_scan_text(text, f"container-rootfs:{path.relative_to(base)}"))
    return findings


def collect_all_findings() -> dict[str, list[str]]:
    """Run every scan; return {surface: findings} (empty list = clean/absent).

    Surfaces (defect 3.6): tracked files, built wheel/sdist in ``dist/``, the
    generated docs site, the live OpenAPI schema, MCP tool descriptions, and —
    when their environment variables point at them — the release body and an
    extracted container rootfs.
    """
    results: dict[str, list[str]] = {
        "tracked": scan_tracked_files(),
        "openapi": scan_openapi_schema(),
        "mcp-descriptions": scan_mcp_descriptions(),
    }

    wheel: list[str] = []
    for w in sorted((REPO_ROOT / "dist").glob("*.whl")):
        wheel.extend(scan_wheel(str(w)))
    sdist: list[str] = []
    for sd in sorted((REPO_ROOT / "dist").glob("*.tar.gz")):
        sdist.extend(scan_sdist(str(sd)))
    results["wheel"] = wheel
    results["sdist"] = sdist

    site_dir = REPO_ROOT / "site"
    results["site"] = scan_site_dir(str(site_dir)) if site_dir.is_dir() else []
    results["release-body"] = scan_release_body(os.environ.get(RELEASE_BODY_ENV))
    results["container-rootfs"] = scan_container_rootfs(os.environ.get(CONTAINER_ROOTFS_ENV))
    return results


def main() -> int:
    results = collect_all_findings()
    for surface, findings in results.items():
        if findings:
            print(f"=== {surface}: FAIL ({len(findings)}) ===")
            for f in findings:
                print(f"  FAIL: {f}")
        else:
            print(f"=== {surface}: OK ===")

    total = sum(len(v) for v in results.values())
    if total:
        print(f"\nFAILED: {total} forbidden pattern(s) found in the public surface.")
        return 1
    print("\nPASSED: public surface is clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
